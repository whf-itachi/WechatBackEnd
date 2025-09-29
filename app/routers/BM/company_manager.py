from fastapi import APIRouter, Query, HTTPException, status
from fastapi.responses import FileResponse
import os
from pathlib import Path
from app.logger import get_logger
from app.config import settings

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
        print("pdf完整的路径为：", file_path)

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
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取PDF文件失败"
        )


PDF_DIR = "/var/www/company/pdf"
CACHE_DIR = "/var/www/company/pdf_cache"


@router.get("/introduce/{filename}/page/{page_num}")
def get_company_pdf_page(filename: str, page_num: int):
    pdf_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 不存在")

    cache_folder = os.path.join(CACHE_DIR, filename)
    os.makedirs(cache_folder, exist_ok=True)

    page_file = os.path.join(cache_folder, f"page_{page_num}.jpg")

    if not os.path.isfile(page_file):
        images = convert_from_path(pdf_path, dpi=72, first_page=page_num, last_page=page_num)
        images[0].save(page_file, "JPEG", quality=70)

    return FileResponse(page_file, media_type="image/jpeg")
