"""
Stage 6: Lint — 知识库健康检查
1. 死链检测：[[链接]] 指向不存在的页面（规则检测）
2. 孤立页面：没有被任何页面引用的页面（规则检测）
3. 空页面：内容过少的页面（规则检测）
4. 矛盾识别：同一概念在不同页面描述不一致（LLM检测）
"""

import re
import json
from pathlib import Path
from openai import OpenAI

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, WIKI_DIR

MIN_CONTENT_LENGTH = 100  # 少于此字符数视为空页面


# ── 主入口 ────────────────────────────────────────────────────────
def lint_knowledge_base(use_llm: bool = True) -> dict:
    """
    扫描整个 wiki/，返回所有问题报告
    use_llm=True 时额外调用 LLM 检测矛盾
    """
    print("[lint] 开始健康检查...")
    wiki_root = Path(WIKI_DIR)

    # 收集所有页面和链接
    pages, links_map = _collect_pages_and_links(wiki_root)

    issues = {
        "dead_links": _check_dead_links(pages, links_map),
        "orphan_pages": _check_orphan_pages(pages, links_map),
        "empty_pages":  _check_empty_pages(wiki_root),
        "contradictions": []
    }

    # LLM 矛盾检测
    if use_llm:
        print("[lint] 调用 LLM 检测矛盾陈述...")
        issues["contradictions"] = _check_contradictions_llm(wiki_root)

    _print_report(issues)
    _save_report(issues, wiki_root)
    return issues


# ── 收集页面名称和链接关系 ────────────────────────────────────────
def _collect_pages_and_links(wiki_root: Path) -> tuple[set, dict]:
    """
    返回：
      pages    = 所有页面名称集合（不含 .md 后缀）
      links_map = {页面名: [该页面引用的链接列表]}
    """
    pages = set()
    links_map = {}

    for md_file in wiki_root.rglob("*.md"):
        name = md_file.stem  # 文件名去掉 .md
        pages.add(name)
        content = md_file.read_text(encoding="utf-8")
        links = re.findall(r"\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]", content)
        links_map[name] = [l.strip() for l in links]

    return pages, links_map


# ── 死链检测 ──────────────────────────────────────────────────────
def _check_dead_links(pages: set, links_map: dict) -> list[dict]:
    """找出所有指向不存在页面的 [[链接]]"""
    dead = []
    for page, links in links_map.items():
        for link in links:
            if link not in pages:
                dead.append({"source": page, "broken_link": link})
    if dead:
        print(f"[lint] ❌ 死链：{len(dead)} 处")
    else:
        print("[lint] ✅ 无死链")
    return dead


# ── 孤立页面检测 ──────────────────────────────────────────────────
def _check_orphan_pages(pages: set, links_map: dict) -> list[str]:
    """找出没有被任何页面引用的页面（排除 README、索引页、insights 问答洞察页）"""
    EXCLUDE = {"README", "tags", "Index"}
    all_linked = {link for links in links_map.values() for link in links}
    
    # insights/ 下的页面是问答归档，天然不会被其他页面引用，排除在外
    insights_pages = {
        md.stem for md in (Path(WIKI_DIR) / "insights").rglob("*.md")
    } if (Path(WIKI_DIR) / "insights").exists() else set()
    
    orphans = [
        p for p in pages
        if p not in all_linked
        and p not in EXCLUDE
        and p not in insights_pages
    ]
    if orphans:
        print(f"[lint] ⚠️  孤立页面：{len(orphans)} 个")
    else:
        print("[lint] ✅ 无孤立页面")
    return orphans


# ── 空页面检测 ────────────────────────────────────────────────────
def _check_empty_pages(wiki_root: Path) -> list[dict]:
    """找出内容过少的页面"""
    empty = []
    for md_file in wiki_root.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        # 去掉 frontmatter 后计算正文长度
        body = re.sub(r"^---.*?---\n", "", content, flags=re.DOTALL).strip()
        if len(body) < MIN_CONTENT_LENGTH:
            empty.append({
                "page": md_file.stem,
                "length": len(body)
            })
    if empty:
        print(f"[lint] ⚠️  空页面：{len(empty)} 个（正文 < {MIN_CONTENT_LENGTH} 字符）")
    else:
        print("[lint] ✅ 无空页面")
    return empty


# ── LLM 矛盾检测 ──────────────────────────────────────────────────
def _check_contradictions_llm(wiki_root: Path) -> list[str]:
    """将整个 wiki 喂给 LLM，让它找出矛盾陈述"""
    # 加载所有 wiki 内容
    parts = []
    for md_file in sorted(wiki_root.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        parts.append(f"--- FILE: {md_file.stem} ---\n{content}")
    full_content = "\n\n".join(parts)

    prompt = f"""请仔细阅读以下知识库内容，找出其中存在的**矛盾陈述**或**不一致描述**。

要求：
- 只报告真正的事实矛盾（同一概念在不同页面有相互冲突的描述）
- 每条矛盾说明：涉及哪些页面、矛盾的具体内容
- 如果没有发现矛盾，直接回答"未发现矛盾"
- 用中文回答，格式：
  1. [页面A] vs [页面B]：矛盾描述...
  2. ...

知识库内容：
{full_content[:80000]}
"""

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2000
    )
    result = response.choices[0].message.content.strip()

    if "未发现矛盾" in result:
        print("[lint] ✅ LLM 未发现矛盾陈述")
        return []
    else:
        contradictions = [line.strip() for line in result.split("\n") if line.strip()]
        print(f"[lint] ⚠️  LLM 发现潜在矛盾：{len(contradictions)} 条")
        return contradictions


# ── 打印报告 ──────────────────────────────────────────────────────
def _print_report(issues: dict):
    print("\n" + "="*50)
    print("📋 知识库健康报告")
    print("="*50)
    print(f"死链：      {len(issues['dead_links'])} 处")
    print(f"孤立页面：  {len(issues['orphan_pages'])} 个")
    print(f"空页面：    {len(issues['empty_pages'])} 个")
    print(f"矛盾陈述：  {len(issues['contradictions'])} 条")

    if issues["dead_links"]:
        print("\n🔗 死链详情：")
        for d in issues["dead_links"]:
            print(f"  [{d['source']}] → [[{d['broken_link']}]] 不存在")

    if issues["orphan_pages"]:
        print("\n🏝️  孤立页面：")
        for p in issues["orphan_pages"]:
            print(f"  - {p}")

    if issues["contradictions"]:
        print("\n⚡ 矛盾陈述：")
        for c in issues["contradictions"]:
            print(f"  {c}")
    print("="*50)


# ── 保存报告到 wiki/index/ ────────────────────────────────────────
def _save_report(issues: dict, wiki_root: Path):
    report_path = wiki_root / "index" / "lint_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(issues, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[lint] 报告已保存：{report_path}")


# ── CLI 入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Karpathy-KB Linter")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 矛盾检测（只做规则检测）")
    args = parser.parse_args()

    lint_knowledge_base(use_llm=not args.no_llm)
