from fastapi import APIRouter, Response, HTTPException, status
from fastapi.responses import FileResponse
import os
from pathlib import Path
from app.logger import get_logger
from app.config import settings

from fastapi.concurrency import run_in_threadpool
import fitz  # PyMuPDF
from datetime import datetime, timedelta
from cachetools import TTLCache
from pdf2image import convert_from_path

router = APIRouter()
logger = get_logger('company_router')


# 配置PDF文件存储目录（可以放在配置文件中）
PDF_STORAGE_DIR = Path(settings.DOCUMENT_PATH)  # 服务器上的指定目录
LOW_QUALITY_DIR = "low"  # 低清晰度文件子目录
HIGH_QUALITY_DIR = "high"  # 高清晰度文件子目录


@router.get("/pdf/{filename}/{quality}")
async def get_pdf_file(filename: str, quality: str):
    try:
        # 确定文件存储路径
        if quality == "high":
            file_dir = PDF_STORAGE_DIR / HIGH_QUALITY_DIR
        else:
            file_dir = PDF_STORAGE_DIR / LOW_QUALITY_DIR

        # 构建完整文件路径
        file_path = file_dir / f"{filename}.pdf"
        logger.error("pdf完整的路径为：", file_path)

        # 验证文件是否存在
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"PDF文件不存在：{filename}.pdf（{quality}）"
            )

        # 验证是否为文件
        if not os.path.isfile(file_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请求的路径不是有效文件"
            )

        # 返回文件
        return FileResponse(
            path=file_path,
            filename=f"{filename}_{quality}.pdf",
            media_type="application/pdf"
        )

    except HTTPException:
        # 重新抛出已定义的HTTP异常
        raise
    except Exception as e:
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取PDF文件失败"
        )


PDF_DIR = "/var/www/company/pdf"
CACHE_DIR = "/var/www/company/pdf_cache"


@router.get("/old/introduce/{filename}/page/{page_num}")
def old_get_company_pdf_page(filename: str, page_num: int):
    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 不存在")

    cache_folder = os.path.join(CACHE_DIR, filename)
    os.makedirs(cache_folder, exist_ok=True)

    page_file = os.path.join(cache_folder, f"page_{page_num}.jpg")

    if not os.path.isfile(page_file):
        # images = convert_from_path(pdf_path, dpi=72, first_page=page_num, last_page=page_num)
        # images[0].save(page_file, "JPEG", quality=70)

        images = convert_from_path(
            pdf_path,
            dpi=90,  # 提高 DPI
            first_page=page_num
        )
        images[0].save(page_file, "PNG")  # 无损保存

    return FileResponse(page_file, media_type="image/jpeg")


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
        dpi=90
    )

    if not img_bytes:
        raise HTTPException(status_code=500, detail="转换PDF页面失败")

    # 加入内存缓存
    memory_cache[cache_key] = img_bytes

    return Response(
        content=img_bytes,
        media_type="image/png"
    )
