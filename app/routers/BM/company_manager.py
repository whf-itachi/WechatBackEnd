from fastapi import APIRouter, Response, HTTPException, BackgroundTasks
from app.utils.enveloping_route import EnvelopingRoute
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from cachetools import TTLCache
from fastapi.concurrency import run_in_threadpool
import fitz  # PyMuPDF
from PIL import Image
import io
from concurrent.futures import ThreadPoolExecutor

from app.logger import get_logger

router = APIRouter(route_class=EnvelopingRoute)
logger = get_logger('company_router')

PDF_DIR = "/var/www/company/pdf"
CACHE_DIR = "/var/www/company/pdf_cache"

MAX_CACHE_AGE = timedelta(days=90)
MEMORY_CACHE_MAX_SIZE = 40
MEMORY_CACHE_TTL = 3600
# 单张图片超过该大小就不进内存缓存，避免个别超大页面把缓存预算吃光
MEMORY_CACHE_MAX_ITEM_BYTES = 1024 * 1024
# 预渲染分批大小，与线程池 worker 数一致，避免一次性把上百个渲染任务堆进内存
PRELOAD_BATCH_SIZE = 2
memory_cache = TTLCache(maxsize=MEMORY_CACHE_MAX_SIZE, ttl=MEMORY_CACHE_TTL)

# 页数缓存：filename -> (源文件 mtime, 页数)。避免每个越界请求都 fitz.open 整本 PDF。
_page_count_cache = {}

# 上次清理磁盘缓存的时间（用时间戳做节流，避免每个 page=1 请求都 walk 整个目录）
_last_clean_at = 0.0
CACHE_CLEAN_INTERVAL = 600  # 秒

# 线程池提升预加载性能
# 注意：渲染内存 ≈ 并发数 × 单页解码位图。198MB / 4 页的 PDF，单页解码约 155MB，
# 4 并发峰值接近 600MB。降到 2 只影响预渲染总耗时，不影响输出画质。
executor = ThreadPoolExecutor(max_workers=2)


def get_pdf_page_count(pdf_path: str) -> int:
    """读取 PDF 页数，按源文件 mtime 缓存。

    越界页码在前端是常态（阅读器会按固定上限请求），
    若每次都 fitz.open 整本 PDF 只为拿长度，等于白付一次全文索引的开销。
    """
    key = os.path.basename(pdf_path)
    try:
        mtime = os.path.getmtime(pdf_path)
    except OSError:
        mtime = 0.0

    cached = _page_count_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    with fitz.open(pdf_path) as doc:
        count = len(doc)
    _page_count_cache[key] = (mtime, count)
    return count

Path(PDF_DIR).mkdir(parents=True, exist_ok=True)
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

# -------------------------------
# 🔧 工具函数
# -------------------------------
def clean_expired_cache():
    """定期清理过期磁盘缓存（带节流，默认 10 分钟内最多跑一次）"""
    global _last_clean_at
    now_ts = time.time()
    if now_ts - _last_clean_at < CACHE_CLEAN_INTERVAL:
        return
    _last_clean_at = now_ts

    now = datetime.now()
    removed = 0
    for root, _, files in os.walk(CACHE_DIR):
        for file in files:
            path = os.path.join(root, file)
            if not os.path.isfile(path):
                continue
            try:
                if now - datetime.fromtimestamp(os.path.getmtime(path)) > MAX_CACHE_AGE:
                    os.remove(path)
                    removed += 1
            except Exception:
                pass
    logger.info(f"清理缓存文件 {removed} 个")
    shrink_mupdf_store()


def shrink_mupdf_store(percent: int = 100):
    """主动收缩 MuPDF 内部 store。

    PyMuPDF 底层的 MuPDF 会缓存解码后的页面/字体/图片，默认上限 256MB，
    且不会随 Document 关闭而释放。长期运行下这块会持续膨胀，
    是 uvicorn 常驻内存缓慢上涨（15 天涨到 ~940MB 后被 OOM）的主要嫌疑。
    """
    try:
        fitz.TOOLS.store_shrink(percent)
    except Exception as e:
        logger.warning(f"收缩 MuPDF store 失败: {e}")


def convert_pdf_page_to_jpeg(pdf_path: str, page_num: int, output_path: str = None, dpi: int = 150):
    """将 PDF 页转换为 progressive JPEG 字节流

    内存说明：pixmap 与 PIL Image 都是大块内存（A4@150dpi 约 6MB/份），
    这里在 finally 中显式释放，避免多线程并发渲染时堆积。
    """
    pix = None
    img = None
    try:
        # with 保证异常路径（如页码越界）也会关闭文档，原来 doc.close() 只在成功路径执行
        with fitz.open(pdf_path) as doc:
            if not (1 <= page_num <= len(doc)):
                raise IndexError("页码超出范围")
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85, progressive=True, optimize=True)
            img_bytes = buf.getvalue()

        if output_path:
            # 原子写：先写 .tmp 再 rename。进程若在写盘途中被 OOM/ kill -9 杀掉，
            # 目标文件要么不存在、要么完整，不会留下半张 JPEG 被后续请求当成有效缓存返回。
            tmp_path = output_path + ".tmp"
            try:
                with open(tmp_path, "wb") as f:
                    f.write(img_bytes)
                os.replace(tmp_path, output_path)
            except Exception:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise

        if len(img_bytes) <= MEMORY_CACHE_MAX_ITEM_BYTES:
            memory_cache[f"{os.path.basename(pdf_path)}/{page_num}"] = img_bytes
        return img_bytes
    except Exception as e:
        logger.error(f"转换 PDF 页出错: {e}")
        return None
    finally:
        # 立即归还大块内存，不等 GC
        if img is not None:
            img.close()
        pix = None
        page = None


async def async_convert_pdf_page(pdf_path, page_num, output_path=None, dpi=150):
    """异步包装"""
    return await run_in_threadpool(
        convert_pdf_page_to_jpeg, pdf_path, page_num, output_path, dpi
    )


def pre_generate_cache(filename: str, max_pages: int = 50):
    """预生成前 N 页缓存（支持并行生成）"""
    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        logger.error(f"PDF 不存在: {pdf_path}")
        return False

    cache_dir = os.path.join(CACHE_DIR, filename)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    with fitz.open(pdf_path) as doc:
        real_pages = len(doc)
    # 缓存真实页数，不能用 min(real_pages, max_pages)，否则会污染越界判断
    _page_count_cache[filename] = (os.path.getmtime(pdf_path), real_pages)
    total = min(real_pages, max_pages)

    pending = []
    for page_num in range(1, total + 1):
        out_path = os.path.join(cache_dir, f"page_{page_num}.jpg")
        key = f"{filename}/{page_num}"
        if key in memory_cache or os.path.exists(out_path):
            continue
        pending.append((page_num, out_path))

    # 分批提交：原来一次性 submit 上百个任务，每个任务都会 open 整个 PDF 并渲染 pixmap，
    # 任务在队列里堆积时内存峰值不可控。按 worker 数分批，跑完一批再提交下一批。
    for i in range(0, len(pending), PRELOAD_BATCH_SIZE):
        batch = pending[i:i + PRELOAD_BATCH_SIZE]
        futures = [
            executor.submit(convert_pdf_page_to_jpeg, pdf_path, page_num, out_path, 150)
            for page_num, out_path in batch
        ]
        for f in futures:
            try:
                f.result()
            except Exception as e:
                logger.error(f"预生成页面失败: {e}")
        # 每批结束主动收缩 MuPDF store，防止解码缓存累积
        shrink_mupdf_store()

    logger.info(f"预生成完成 {filename} 的前 {total} 页缓存（本次生成 {len(pending)} 页）")
    return True


# -------------------------------
# 📄 API 路由
# -------------------------------
@router.get("/introduce/{filename}/page/{page_num}")
async def get_company_pdf_page(filename: str, page_num: int):
    """返回 PDF 第 N 页的 progressive JPEG 图片"""
    if page_num == 1:
        await run_in_threadpool(clean_expired_cache)

    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 不存在")

    # 越界页码直接拒绝：不再为它打开整本 PDF 并触发解码。
    # 前端阅读器会按固定上限盲目请求，这条路径命中率很高。
    try:
        total_pages = await run_in_threadpool(get_pdf_page_count, pdf_path)
    except Exception as e:
        logger.error(f"读取 PDF 页数失败 {filename}: {e}")
        raise HTTPException(status_code=500, detail="PDF 无法解析")
    if not (1 <= page_num <= total_pages):
        logger.info(f"页码越界 {filename}/{page_num}，总页数 {total_pages}")
        raise HTTPException(status_code=404, detail="页码超出范围")

    cache_dir = os.path.join(CACHE_DIR, filename)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"page_{page_num}.jpg")
    cache_key = f"{filename}/{page_num}"

    # 1️⃣ 内存缓存
    if cache_key in memory_cache:
        logger.debug(f"内存缓存命中 {cache_key}")
        return Response(content=memory_cache[cache_key], media_type="image/jpeg")

    # 2️⃣ 磁盘缓存
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "rb") as f:
                img_bytes = f.read()
                memory_cache[cache_key] = img_bytes
                logger.debug(f"磁盘缓存命中 {cache_key}")
                return Response(content=img_bytes, media_type="image/jpeg")
        except Exception as e:
            logger.error(f"读取缓存失败: {e}")

    # 3️⃣ 实时生成
    logger.info(f"生成新页面 {cache_key}")
    img_bytes = await async_convert_pdf_page(pdf_path, page_num, cache_file, 150)
    if not img_bytes:
        raise HTTPException(status_code=500, detail="生成图片失败")

    return Response(content=img_bytes, media_type="image/jpeg")


@router.post("/introduce/{filename}/preload")
async def preload_company_pdf(filename: str, background_tasks: BackgroundTasks):
    """异步预生成前若干页缓存"""
    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 不存在")

    def task():
        logger.info(f"开始后台缓存预热: {filename}")
        ok = pre_generate_cache(filename, 80)
        if ok:
            logger.info(f"后台缓存生成完成: {filename}")
        else:
            logger.error(f"后台缓存生成失败: {filename}")

    background_tasks.add_task(task)
    return {"status": "ok", "msg": "已启动后台缓存预热任务"}
