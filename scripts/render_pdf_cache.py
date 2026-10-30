#!/usr/bin/env python3
"""预渲染 PDF 为逐页 JPEG，供后端直接读取或 nginx 静态直出。

背景
----
二维码物料长期有效，但原实现是每次扫码都由 FastAPI 用 PyMuPDF 逐页渲染：

    扫码 -> SPA -> GET /BM/company/introduce/{name}/page/N -> fitz 渲染 -> 返回

渲染是纯函数：同一个 PDF、同一页、同样的 dpi/quality，输出字节永远相同。
把它绑在请求上，等于每个访客都要重新算一遍同样的图。本脚本把渲染时机
从「请求时」前移到「发布时」。

三种模式
--------
--auto    推荐。逐个 PDF 比对源文件 mtime + size 与 meta.json 中的记录：
          未变的直接跳过（耗时几毫秒），变了的清空该 PDF 的目录后重渲。
          已经完整且未更新时，整个命令不到 1 秒。
--force   无视记录，全部重渲。改了 dpi/quality 时用。
（默认）   不删任何东西，只补缺失的页。首次填充用这个。

用法
----
    source myenv/bin/activate
    python scripts/render_pdf_cache.py --all --auto        # 发布后调用（推荐）
    python scripts/render_pdf_cache.py DMM_25.pdf --auto  # 只处理一个
    python scripts/render_pdf_cache.py --all --force      # 全量重渲
    python scripts/render_pdf_cache.py --all --purge      # 只清缓存不渲染

产物
----
    <cache-dir>/<filename>/page_1.jpg ...
    <cache-dir>/<filename>/meta.json   含 pages / dpi / source_mtime / source_size
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

DEFAULT_PDF_DIR = "/var/www/company/pdf"
DEFAULT_CACHE_DIR = "/var/www/company/pdf_cache"


def load_meta(out_dir: Path):
    path = out_dir / "meta.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def source_stamp(pdf_path: Path) -> dict:
    st = pdf_path.stat()
    return {"source_mtime": int(st.st_mtime), "source_size": st.st_size}


def existing_pages(out_dir: Path) -> dict:
    """已存在的页文件 {页码: 路径}"""
    found = {}
    for path in out_dir.glob("page_*.jpg"):
        try:
            found[int(path.stem.split("_", 1)[1])] = path
        except (IndexError, ValueError):
            continue
    return found


def plan(out_dir: Path, pdf_path: Path, pages: int, mode: str):
    """决定是否需要清空目录，以及要渲染哪些页。

    返回 (wipe, todo, reason)
    """
    present = existing_pages(out_dir)
    stale = [n for n in present if n > pages]  # PDF 页数变少后的残留

    if mode == "force":
        return True, list(range(1, pages + 1)), "force"

    if mode == "auto":
        old = load_meta(out_dir)
        if old is None:
            return True, list(range(1, pages + 1)), "无 meta.json"
        now = source_stamp(pdf_path)
        if old.get("source_mtime") != now["source_mtime"] or old.get("source_size") != now["source_size"]:
            return True, list(range(1, pages + 1)), "源文件已更新"
        if old.get("pages") != pages:
            return True, list(range(1, pages + 1)), "页数变化"
        missing = [n for n in range(1, pages + 1) if n not in present]
        if missing:
            return False, missing, f"缺 {len(missing)} 页"
        return False, [], "未变化"

    # 默认模式：只补缺失，从不删除
    todo = [n for n in range(1, pages + 1) if n not in present]
    if stale:
        return False, todo, f"补 {len(todo)} 页（另有 {len(stale)} 张多余页未清理）"
    return False, todo, f"补 {len(todo)} 页" if todo else "已完整"


def render_one(pdf_path: Path, out_dir: Path, dpi: int, quality: int, mode: str) -> dict:
    """渲染单个 PDF，返回统计信息。"""
    started = time.time()

    with fitz.open(pdf_path) as doc:
        pages = len(doc)

    out_dir.mkdir(parents=True, exist_ok=True)
    wipe, todo, reason = plan(out_dir, pdf_path, pages, mode)

    if wipe:
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    if todo:
        with fitz.open(pdf_path) as doc:
            for number in todo:
                target = out_dir / f"page_{number}.jpg"
                img = None
                pix = None
                page = None
                try:
                    page = doc.load_page(number - 1)
                    pix = page.get_pixmap(dpi=dpi)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    # 原子写：.tmp 写完再 rename，中途被杀不会留下半个 JPEG。
                    # 后缀不是 .jpg，不会被 existing_pages() 的 glob("page_*.jpg") 命中。
                    tmp = target.with_suffix(".jpg.tmp")
                    img.save(tmp, "JPEG", quality=quality, progressive=True, optimize=True)
                    os.replace(tmp, target)
                    generated += 1
                finally:
                    # 逐页显式释放，避免整本 PDF 渲染过程中内存累积
                    if img is not None:
                        img.close()
                    pix = None
                    page = None

    # 清理页数变少后残留的旧页，否则 nginx 直出时可能返回已不存在的页
    present = existing_pages(out_dir)
    removed = 0
    for number, path in present.items():
        if number > pages:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    meta = {
        "filename": pdf_path.name,
        "pages": pages,
        "dpi": dpi,
        "quality": quality,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_ms": int((time.time() - started) * 1000),
        **source_stamp(pdf_path),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "meta": meta,
        "generated": generated,
        "action": "重渲" if wipe else ("补页" if todo else "跳过"),
        "reason": reason,
        "removed": removed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="预渲染 PDF 为逐页 JPEG")
    parser.add_argument("filename", nargs="?", help="PDF 文件名，如 DMM_25.pdf")
    parser.add_argument("--all", action="store_true", help="处理 PDF 目录下所有文件")
    parser.add_argument("--auto", action="store_true", help="仅重渲源文件有变化的 PDF（推荐）")
    parser.add_argument("--force", action="store_true", help="强制重渲全部")
    parser.add_argument("--purge", action="store_true", help="只删除缓存，不渲染")
    parser.add_argument("--pdf-dir", default=DEFAULT_PDF_DIR)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--quality", type=int, default=85)
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    cache_dir = Path(args.cache_dir)

    if args.all:
        targets = sorted(pdf_dir.glob("*.pdf"))
    elif args.filename:
        targets = [pdf_dir / args.filename]
    else:
        parser.error("需要指定文件名，或使用 --all")

    if args.purge:
        removed = 0
        for pdf_path in targets:
            target = cache_dir / pdf_path.name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                removed += 1
        print(f"已删除 {removed} 个缓存目录")
        return 0

    if not targets:
        print(f"未找到任何 PDF: {pdf_dir}")
        return 1

    mode = "force" if args.force else ("auto" if args.auto else "skip")
    failed = 0
    total_generated = 0
    overall = time.time()

    for pdf_path in targets:
        if not pdf_path.is_file():
            print(f"[跳过] 文件不存在: {pdf_path}")
            failed += 1
            continue
        try:
            result = render_one(pdf_path, cache_dir / pdf_path.name, args.dpi, args.quality, mode)
        except Exception as exc:  # 单个文件失败不影响其余文件
            print(f"[失败] {pdf_path.name}: {exc}")
            failed += 1
            continue

        meta = result["meta"]
        total_generated += result["generated"]
        extra = f"，清理多余页 {result['removed']}" if result["removed"] else ""
        print(
            f"[{result['action']}] {pdf_path.name} {meta['pages']} 页，"
            f"新生成 {result['generated']}{extra}，"
            f"耗时 {meta['elapsed_ms']}ms（{result['reason']}）"
        )

    print(f"合计新生成 {total_generated} 页，总耗时 {int((time.time() - overall) * 1000)}ms")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
