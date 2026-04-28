"""
Obsidian 兼容性处理 + Export 导出功能
支持导出格式：PDF、HTML、Markdown 打包
"""

import os
import shutil
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import WIKI_DIR


# ── Markdown 打包导出 ─────────────────────────────────────────────
def export_markdown(output_path: str = "export/markdown.zip"):
    """将整个 wiki/ 打包为 .zip"""
    import zipfile
    
    wiki_root = Path(WIKI_DIR)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for md_file in wiki_root.rglob("*.md"):
            zipf.write(md_file, md_file.relative_to(wiki_root.parent))
    
    print(f"[export] ✅ Markdown 已打包：{out_path}")
    return out_path


# ── HTML 导出 ─────────────────────────────────────────────────────
def export_html(output_dir: str = "export/html"):
    """将所有 .md 转为 HTML，保留双向链接"""
    try:
        import markdown
    except ImportError:
        print("[export] ❌ 缺少依赖，请安装：pip install markdown")
        return
    
    wiki_root = Path(WIKI_DIR)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    md_converter = markdown.Markdown(extensions=['extra', 'meta', 'toc'])
    
    for md_file in wiki_root.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        
        # 转换 [[双向链接]] 为 HTML <a> 标签
        import re
        content = re.sub(
            r'\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]',
            lambda m: f'<a href="{m.group(1)}.html">{m.group(2) or m.group(1)}</a>',
            content
        )
        
        html = md_converter.convert(content)
        
        # 包装成完整 HTML
        full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{md_file.stem}</title>
    <style>
        body {{ max-width: 800px; margin: 40px auto; font-family: sans-serif; line-height: 1.6; }}
        a {{ color: #0066cc; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
{html}
</body>
</html>"""
        
        out_file = out_dir / md_file.relative_to(wiki_root).with_suffix(".html")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(full_html, encoding="utf-8")
    
    print(f"[export] ✅ HTML 已生成：{out_dir}")
    return out_dir


# ── PDF 导出（需要 wkhtmltopdf 或 weasyprint）────────────────────
def export_pdf(output_path: str = "export/knowledge_base.pdf"):
    """将整个知识库合并为单个 PDF"""
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        print("[export] ❌ 缺少依赖，请安装：pip install weasyprint")
        print("    或者安装 wkhtmltopdf：https://wkhtmltopdf.org/")
        return
    
    # 先生成 HTML
    html_dir = export_html("export/html_temp")
    
    # 合并所有 HTML 为一个大文件
    wiki_root = Path(WIKI_DIR)
    combined_html = ["<html><head><meta charset='UTF-8'></head><body>"]
    
    for md_file in sorted(wiki_root.rglob("*.md")):
        html_file = Path("export/html_temp") / md_file.relative_to(wiki_root).with_suffix(".html")
        if html_file.exists():
            combined_html.append(html_file.read_text(encoding="utf-8"))
            combined_html.append("<hr style='page-break-after: always;'>")
    
    combined_html.append("</body></html>")
    
    # 生成 PDF
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    HTML(string="".join(combined_html)).write_pdf(out_path)
    
    # 清理临时文件
    shutil.rmtree("export/html_temp", ignore_errors=True)
    
    print(f"[export] ✅ PDF 已生成：{out_path}")
    return out_path


# ── CLI 入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export Knowledge Base")
    parser.add_argument("--format", choices=["markdown", "html", "pdf"], required=True)
    parser.add_argument("--output", help="输出路径（可选）")
    args = parser.parse_args()
    
    if args.format == "markdown":
        export_markdown(args.output or "export/markdown.zip")
    elif args.format == "html":
        export_html(args.output or "export/html")
    elif args.format == "pdf":
        export_pdf(args.output or "export/knowledge_base.pdf")
