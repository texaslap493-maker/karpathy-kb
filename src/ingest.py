"""
Stage 1: Ingest — 文档加载与预处理
支持格式：PDF、网页URL（转Markdown）、纯文本/Markdown笔记
输出：统一保存到 raw/ 对应子目录，内容为纯文本
"""

import os
import re
import sys
import requests
import urllib.request
from pathlib import Path

# ── 可选依赖，缺失时给出提示 ──────────────────────────────────────
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from markdownify import markdownify as md
    HAS_MARKDOWNIFY = True
except ImportError:
    HAS_MARKDOWNIFY = False

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import RAW_DIR


# ── PDF ───────────────────────────────────────────────────────────
def ingest_pdf(pdf_path: str) -> str:
    """解析 PDF，返回纯文本；同时保存到 raw/papers/"""
    if not HAS_PYMUPDF:
        raise ImportError("请先安装 PyMuPDF：pip install pymupdf")

    doc = fitz.open(pdf_path)
    text = "\n\n".join(page.get_text() for page in doc)
    doc.close()

    out_path = _save_raw(text, Path(pdf_path).stem + ".txt", "papers")
    print(f"[ingest] PDF → {out_path}  ({len(text)} 字符)")
    return text


# ── 网页 URL ──────────────────────────────────────────────────────
def ingest_url(url: str) -> str:
    """抓取网页，转为 Markdown；保存到 raw/webclips/"""
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    html = resp.text

    # 用 BeautifulSoup 先删除 <script> <style> 标签，再转 Markdown
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()  # 直接从 DOM 删除
        clean_html = str(soup)
    except ImportError:
        clean_html = html

    if HAS_MARKDOWNIFY:
        text = md(clean_html, heading_style="ATX")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    else:
        text = re.sub(r"<[^>]+>", "", clean_html)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    slug = re.sub(r"[^\w\-]", "_", url.split("//")[-1])[:60]
    out_path = _save_raw(text, slug + ".md", "webclips")
    print(f"[ingest] URL → {out_path}  ({len(text)} 字符)")
    return text


# ── 本地文本 / Markdown ───────────────────────────────────────────
def ingest_text(file_path: str) -> str:
    """读取本地 .txt / .md 文件；复制到 raw/notes/"""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    out_path = _save_raw(text, Path(file_path).name, "notes")
    print(f"[ingest] 文本 → {out_path}  ({len(text)} 字符)")
    return text


# ── 批量扫描 raw/ 目录，返回所有已摄入内容 ────────────────────────
def load_all_raw() -> dict[str, str]:
    """
    遍历 raw/ 下所有文件，返回 {相对路径: 文本内容}
    供 compiler.py 使用
    """
    result = {}
    raw_root = Path(RAW_DIR)
    for fp in sorted(raw_root.rglob("*")):
        if fp.is_file() and fp.suffix in {".txt", ".md"}:
            try:
                text = fp.read_text(encoding="utf-8")
                result[str(fp)] = text
            except Exception as e:
                print(f"[ingest] 跳过 {fp}：{e}")
    print(f"[ingest] 共加载 {len(result)} 个文件")
    return result


# ── 内部工具 ──────────────────────────────────────────────────────
def _save_raw(text: str, filename: str, subdir: str) -> Path:
    out_dir = Path(RAW_DIR) / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(text, encoding="utf-8")
    return out_path


# ── CLI 快速测试 ──────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Karpathy-KB Ingest")
    parser.add_argument("--pdf",  help="导入 PDF 文件路径")
    parser.add_argument("--url",  help="导入网页 URL")
    parser.add_argument("--text", help="导入本地文本/Markdown 文件")
    args = parser.parse_args()

    if args.pdf:
        ingest_pdf(args.pdf)
    elif args.url:
        ingest_url(args.url)
    elif args.text:
        ingest_text(args.text)
    else:
        parser.print_help()
