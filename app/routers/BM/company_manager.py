from fastapi import APIRouter, Response, HTTPException, BackgroundTasks
import os
from pathlib import Path
from app.logger import get_logger

from fastapi.concurrency import run_in_threadpool
import fitz  # PyMuPDF
from datetime import datetime, timedelta
from cachetools import TTLCache

router = APIRouter()
logger = get_logger('company_router')

PDF_DIR = "/var/www/company/pdf"
CACHE_DIR = "/var/www/company/pdf_cache"


MAX_CACHE_AGE = timedelta(days=7)  # 磁盘缓存过期时间

# 内存缓存配置
MEMORY_CACHE_MAX_SIZE = 100  # 最多缓存100个页面
MEMORY_CACHE_TTL = 3600  # 内存缓存过期时间(秒)
memory_cache = TTLCache(maxsize=MEMORY_CACHE_MAX_SIZE, ttl=MEMORY_CACHE_TTL)

# 确保目录存在
Path(PDF_DIR).mkdir(parents=True, exist_ok=True)
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


def clean_expired_cache():
    """清理过期的磁盘缓存文件"""
    now = datetime.now()
    for root, dirs, files in os.walk(CACHE_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            if now - file_mtime > MAX_CACHE_AGE:
                os.remove(file_path)
                # 从内存缓存中移除
                cache_key = f"{os.path.basename(root)}/{file.split('_')[1].split('.')[0]}"
                if cache_key in memory_cache:
                    del memory_cache[cache_key]

    # 清理空目录
    for root, dirs, files in os.walk(CACHE_DIR, topdown=False):
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)


def convert_pdf_page(pdf_path, page_num, output_path=None, dpi=90):
    """转换PDF页面为图片，返回图片字节数据，可选保存到磁盘"""
    try:
        doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > len(doc):
            raise IndexError("页面编号超出范围")

        page = doc[page_num - 1]  # PyMuPDF页码从0开始
        pix = page.get_pixmap(dpi=dpi)

        # 获取图片字节数据
        img_bytes = pix.tobytes()

        # 如果指定了输出路径，保存到磁盘
        if output_path:
            pix.save(output_path)

        doc.close()
        return img_bytes
    except Exception as e:
        logger.error(f"转换PDF页面出错: {e}")
        return None


async def async_convert_pdf_page(pdf_path, page_num, output_path=None, dpi=90):
    """异步转换PDF页面"""
    return await run_in_threadpool(
        convert_pdf_page,
        pdf_path,
        page_num,
        output_path,
        dpi
    )


def pre_generate_cache(filename, max_pages=50):
    """预生成PDF前N页的缓存"""
    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        return False

    cache_folder = os.path.join(CACHE_DIR, filename)
    Path(cache_folder).mkdir(parents=True, exist_ok=True)

    try:
        doc = fitz.open(pdf_path)
        total_pages = min(len(doc), max_pages)
        doc.close()

        for page_num in range(1, total_pages + 1):
            page_file = os.path.join(cache_folder, f"page_{page_num}.png")
            cache_key = f"{filename}/{page_num}"

            # 如果内存和磁盘都没有缓存，才生成
            if cache_key not in memory_cache and not os.path.exists(page_file):
                img_bytes = convert_pdf_page(pdf_path, page_num, page_file)
                if img_bytes:
                    memory_cache[cache_key] = img_bytes
        return True
    except Exception as e:
        logger.error(f"预生成缓存出错: {e}")
        return False


@router.get("/introduce/{filename}/page/{page_num}")
async def get_company_pdf_page(filename: str, page_num: int):
    # 定期清理过期缓存
    if page_num == 1:
        await run_in_threadpool(clean_expired_cache)

    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 不存在")

    cache_folder = os.path.join(CACHE_DIR, filename)
    Path(cache_folder).mkdir(parents=True, exist_ok=True)

    page_file = os.path.join(cache_folder, f"page_{page_num}.png")
    cache_key = f"{filename}/{page_num}"  # 内存缓存键

    # 1. 先检查内存缓存
    if cache_key in memory_cache:
        logger.error(f"内存缓存命中: {cache_key}")
        return Response(
            content=memory_cache[cache_key],
            media_type="image/png"
        )

    # 2. 检查磁盘缓存
    if os.path.isfile(page_file):
        logger.error(f"磁盘缓存命中: {cache_key}")
        # 读取磁盘文件并加入内存缓存
        try:
            with open(page_file, "rb") as f:
                img_bytes = f.read()
                memory_cache[cache_key] = img_bytes  # 加入内存缓存
            return Response(
                content=img_bytes,
                media_type="image/png"
            )
        except Exception as e:
            logger.error(f"读取缓存文件出错: {e}")

    # 3. 缓存不存在，生成新的
    try:
        logger.error(f"缓存未命中，生成新内容: {cache_key}")
        doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            raise HTTPException(status_code=404, detail="页面不存在")
        doc.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理PDF时出错: {str(e)}")

    # 生成图片并同时更新内存和磁盘缓存
    img_bytes = await async_convert_pdf_page(
        pdf_path,
        page_num,
        page_file,  # 保存到磁盘
        dpi=150
    )

    if not img_bytes:
        raise HTTPException(status_code=500, detail="转换PDF页面失败")

    # 加入内存缓存
    memory_cache[cache_key] = img_bytes

    return Response(
        content=img_bytes,
        media_type="image/png"
    )


@router.post("/introduce/{filename}/preload")
async def preload_company_pdf(filename: str, background_tasks: BackgroundTasks):
    """
    异步预生成 PDF 缓存（由前端在首次加载时触发）
    """
    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 不存在")

    def background_task():
        logger.info(f"开始后台预生成缓存: {filename}")
        success = pre_generate_cache(filename, max_pages=100)
        if success:
            logger.info(f"PDF 缓存预生成完成: {filename}")
        else:
            logger.error(f"PDF 缓存预生成失败: {filename}")

    background_tasks.add_task(background_task)
    return {"status": "ok", "msg": "后台正在生成缓存"}
