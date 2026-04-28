"""
Karpathy-KB 主程序入口
用法：
  python app.py ingest --pdf raw/papers/xxx.pdf   # 导入 PDF 文件
  python app.py ingest --url https://example.com  # 导入网页（自动转为 Markdown）
  python app.py ingest --text raw/notes/xxx.md    # 导入本地文本/Markdown 文件
  python app.py compile                           # 编译知识库：读取 raw/ → 生成 wiki/
  python app.py query                             # 启动问答（save 保存对话 | wiki 生成wiki页面 | clear 清空历史 | q 退出）
  python app.py query --list                      # 列出所有历史对话
  python app.py query --resume session_xxx.json   # 继续某次历史对话
  python app.py query --show session_xxx.json     # 格式化显示某次历史对话内容
  python app.py lint                              # 健康检查：死链 + 孤立页面 + 空页面 + LLM矛盾检测（消耗token）
  python app.py lint --no-llm                     # 健康检查：仅规则检测（死链/孤立/空页面），跳过LLM矛盾检测，速度快且免费
  python app.py export --format markdown          # 导出为 Markdown 压缩包
  python app.py export --format html              # 导出为 HTML 静态网站
  python app.py export --format pdf               # 导出为 PDF 文件
"""

import argparse
import sys


def cmd_ingest(args):
    from src.ingest import ingest_pdf, ingest_url, ingest_text
    if args.pdf:
        ingest_pdf(args.pdf)
    elif args.url:
        ingest_url(args.url)
    elif args.text:
        ingest_text(args.text)
    else:
        print("请指定 --pdf / --url / --text")
        sys.exit(1)


def cmd_compile(args):
    from src.compiler import compile_knowledge_base
    compile_knowledge_base()


def cmd_query(args):
    from src.query_engine import KarpathyKnowledgeBase
    import json
    from pathlib import Path
    
    # 如果指定了 --list，列出所有历史对话
    if args.list:
        sessions_dir = Path("outputs/sessions")
        if sessions_dir.exists():
            sessions = sorted(sessions_dir.glob("*.json"))
            if sessions:
                print("\n历史对话列表：")
                for s in sessions:
                    print(f"  - {s.name}")
            else:
                print("暂无历史对话")
        return
    
    # 如果指定了 --resume，加载历史对话
    resume_file = None
    if args.resume:
        session_path = Path("outputs/sessions") / args.resume
        if session_path.exists():
            history = json.loads(session_path.read_text(encoding="utf-8"))
            kb = KarpathyKnowledgeBase(resume_from=args.resume)
            kb.chat_history = history
            print(f"[query] 已加载历史对话：{args.resume}，共 {len(history)} 条消息")
        else:
            print(f"[query] ❌ 找不到对话文件：{args.resume}")
            return
    else:
        kb = KarpathyKnowledgeBase()
    
    print("\n知识库已就绪！输入问题开始问答")
    print("命令：save 保存对话 | wiki 生成wiki页面 | clear 清空历史 | q 退出\n")

    while True:
        user_input = input("你：").strip()
        if not user_input:
            continue
        if user_input.lower() == "q":
            break
        elif user_input.lower() == "save":
            kb.save_session()
        elif user_input.lower() == "wiki":
            if not kb.session_file:
                print("[query] ⚠️  请先使用 'save' 命令保存对话")
            else:
                kb.generate_wiki_page()
        elif user_input.lower() == "clear":
            kb.clear_history()
        else:
            answer = kb.query(user_input)
            print(f"\nAI：{answer}\n")


def cmd_lint(args):
    from src.linter import lint_knowledge_base
    lint_knowledge_base(use_llm=not args.no_llm)


def cmd_export(args):
    from src.obsidian_compat import export_markdown, export_html, export_pdf
    if args.format == "markdown":
        export_markdown(args.output or "export/markdown.zip")
    elif args.format == "html":
        export_html(args.output or "export/html")
    elif args.format == "pdf":
        export_pdf(args.output or "export/knowledge_base.pdf")


# ── 参数解析 ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="karpathy-kb",
        description="Karpathy 风格长上下文知识库"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ingest
    p_ingest = sub.add_parser("ingest", help="导入原始资料")
    p_ingest.add_argument("--pdf",  help="PDF 文件路径")
    p_ingest.add_argument("--url",  help="网页 URL")
    p_ingest.add_argument("--text", help="本地文本/Markdown 文件")

    # compile
    sub.add_parser("compile", help="编译知识库（raw/ → wiki/）")

    # query
    p_query = sub.add_parser("query", help="长上下文问答")
    p_query.add_argument("--list", action="store_true", help="列出所有历史对话")
    p_query.add_argument("--show", help="格式化显示某次历史对话（文件名，如：session_20260414_224732.json）")
    p_query.add_argument("--resume", help="继续某个历史对话（文件名，如：session_20260414_224732.json）")

    # lint
    p_lint = sub.add_parser("lint", help="知识库健康检查")
    p_lint.add_argument("--no-llm", action="store_true", help="跳过 LLM 矛盾检测")

    # export
    p_export = sub.add_parser("export", help="导出知识库")
    p_export.add_argument("--format", choices=["markdown", "html", "pdf"], required=True, help="导出格式")
    p_export.add_argument("--output", help="输出路径（可选）")

    args = parser.parse_args()

    dispatch = {
        "ingest":  cmd_ingest,
        "compile": cmd_compile,
        "query":   cmd_query,
        "lint":    cmd_lint,
        "export":  cmd_export,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
