from fastapi import APIRouter, Response, HTTPException, BackgroundTasks
import os
from pathlib import Path
from datetime import datetime, timedelta
from cachetools import TTLCache
from fastapi.concurrency import run_in_threadpool
import fitz  # PyMuPDF
from PIL import Image
import io
from concurrent.futures import ThreadPoolExecutor

from app.logger import get_logger

router = APIRouter()
logger = get_logger('company_router')

PDF_DIR = "/var/www/company/pdf"
CACHE_DIR = "/var/www/company/pdf_cache"

MAX_CACHE_AGE = timedelta(days=7)
MEMORY_CACHE_MAX_SIZE = 100
MEMORY_CACHE_TTL = 3600
memory_cache = TTLCache(maxsize=MEMORY_CACHE_MAX_SIZE, ttl=MEMORY_CACHE_TTL)

# 线程池提升预加载性能
executor = ThreadPoolExecutor(max_workers=4)

Path(PDF_DIR).mkdir(parents=True, exist_ok=True)
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

# -------------------------------
# 🔧 工具函数
# -------------------------------
def clean_expired_cache():
    """定期清理过期磁盘缓存"""
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


def convert_pdf_page_to_jpeg(pdf_path: str, page_num: int, output_path: str = None, dpi: int = 150):
    """将 PDF 页转换为 progressive JPEG 字节流"""
    try:
        doc = fitz.open(pdf_path)
        if not (1 <= page_num <= len(doc)):
            raise IndexError("页码超出范围")
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, progressive=True, optimize=True)
        img_bytes = buf.getvalue()

        if output_path:
            with open(output_path, "wb") as f:
                f.write(img_bytes)

        memory_cache[f"{os.path.basename(pdf_path)}/{page_num}"] = img_bytes
        doc.close()
        return img_bytes
    except Exception as e:
        logger.error(f"转换 PDF 页出错: {e}")
        return None


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

    doc = fitz.open(pdf_path)
    total = min(len(doc), max_pages)
    doc.close()

    futures = []
    for page_num in range(1, total + 1):
        out_path = os.path.join(cache_dir, f"page_{page_num}.jpg")
        key = f"{filename}/{page_num}"
        if key in memory_cache or os.path.exists(out_path):
            continue
        futures.append(executor.submit(convert_pdf_page_to_jpeg, pdf_path, page_num, out_path, 150))

    for f in futures:
        f.result()

    logger.info(f"预生成完成 {filename} 的前 {total} 页缓存")
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
