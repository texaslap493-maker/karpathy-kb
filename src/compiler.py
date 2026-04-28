"""
Stage 2: Compiler — ⭐ 核心知识编译器（增量编译）
读取 raw/ 全部内容 → 调用长上下文 LLM → 生成结构化 wiki/
增量编译：只编译新增/修改的文件，节省时间和API成本
"""

import os
import re
import json
import hashlib
from pathlib import Path
from openai import OpenAI

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, WIKI_DIR, RAW_DIR
from src.ingest import load_all_raw


# 编译状态记录文件
COMPILE_STATE_FILE = Path(WIKI_DIR) / "index" / "compile_state.json"


# ── Compilation Prompt ──────────────────────────────
COMPILATION_PROMPT = """
你是一个知识编译器。请将以下原始资料整理成结构化的Markdown知识库。

**重要规则**：
- 所有输出内容必须使用中文，包括页面标题、摘要、说明等（即使原始资料是英文）
- 文件名使用下划线连接，不使用空格（如：Geoffrey_Hinton.md，不是 Geoffrey Hinton.md）
- 人名、专有名词保留英文原名，但说明用中文

**关于双向链接 [[概念]]**：
- 只为真正的知识概念创建链接（如：人名、技术术语、理论）
- 不要为以下内容创建链接：URL、DOI、ISBN、PMID、文件路径、网页标题
- 每个 [[链接]] 必须对应一个实际生成的 .md 文件
- 如果不确定是否要创建某个概念页面，就不要写 [[链接]]

**关于已有页面（重要）**：
{existing_context}

- 如果新资料涉及上述已有页面的概念，在已有页面基础上补充新信息，用 ===UPDATE: concepts/页面名.md=== 标记
- 只为新资料中出现的、完全陌生的概念创建新页面，用 ===FILE: concepts/新概念.md=== 标记
- 不要重复创建已有页面

## 任务要求：

1. **实体识别**：提取所有重要概念、人名、术语，创建独立页面
2. **自动链接**：使用[[双向链接]]语法连接相关概念
3. **层级结构**：
   - 每个实体一个Markdown文件
   - Frontmatter包含：title, date, tags, sources
   - 正文包含：摘要、详细说明、相关链接、待探索问题
4. **冲突处理**：如果多个来源信息矛盾，保留并标注争议点
5. **索引生成**：创建README.md作为知识库入口

## 输出格式要求：

你需要输出多个 Markdown 文件，每个文件用以下格式分隔：

```
===FILE: concepts/注意力机制.md===
---
title: "注意力机制"
date: 2026-04-13
tags: ["深度学习", "Transformer"]
sources: ["神经网络与深度学习.pdf"]
---

# 注意力机制

## 摘要
一种在[[深度学习]]中让模型关注输入特定部分的机制...

## 详细说明
...

## 相关概念
- [[Transformer]]
- [[自注意力]]

## 待探索
- [ ] 与RNN的详细对比
```

**重要**：
- 每个文件开头必须是 `===FILE: 相对路径===`
- 概念页面放在 `concepts/`
- 人物页面放在 `people/`
- 必须生成一个 `README.md` 作为索引入口

## 原始资料：

{raw_content}

---

现在开始编译，输出所有 Markdown 文件：
"""


# ── 增量编译：计算文件哈希 ────────────────────────────────────────
def _file_hash(file_path: str) -> str:
    """计算文件内容的 MD5 哈希"""
    try:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except:
        return ""


def _load_compile_state() -> dict:
    """加载上次编译状态"""
    if COMPILE_STATE_FILE.exists():
        return json.loads(COMPILE_STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_compile_state(state: dict):
    """保存编译状态"""
    COMPILE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMPILE_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_changed_files(raw_files: dict) -> dict:
    """返回新增或修改的文件"""
    old_state = _load_compile_state()
    changed = {}
    
    for path, content in raw_files.items():
        current_hash = hashlib.md5(content.encode()).hexdigest()
        if path not in old_state or old_state[path] != current_hash:
            changed[path] = content
            old_state[path] = current_hash
    
    # 保存新状态
    _save_compile_state(old_state)
    return changed


# ── 主编译函数（增量） ────────────────────────────────────────────
def compile_knowledge_base(max_tokens=100000):
    """
    增量编译：只编译新增/修改的文件
    第一次运行时自动全量编译
    """
    print("[compiler] 加载原始资料...")
    raw_files = load_all_raw()
    
    if not raw_files:
        print("[compiler] ❌ raw/ 目录为空，请先用 ingest.py 导入资料")
        return
    
    # 增量检测
    changed_files = _get_changed_files(raw_files)
    
    if not changed_files:
        print("[compiler] ✅ 所有文件已是最新，无需重新编译")
        return
    
    print(f"[compiler] 检测到 {len(changed_files)} 个新增/修改文件（共 {len(raw_files)} 个）")
    for path in changed_files.keys():
        print(f"  - {path}")
    
    # 拼接变化的内容
    raw_content = "\n\n".join(
        f"### 文件：{path}\n{content[:50000]}"
        for path, content in changed_files.items()
    )
    
    # 列出已有 wiki 页面，并加载可能相关的页面内容
    wiki_root = Path(WIKI_DIR)
    existing_pages = {}
    for f in wiki_root.rglob("*.md"):
        if f.name == "README.md" or "index" in f.parts or "outputs" in f.parts:
            continue
        page_name = f.stem
        # 如果新资料里提到了这个页面名，就加载它的内容
        if page_name in raw_content or any(keyword in page_name for keyword in ["神经网络", "深度学习", "机器学习"]):
            try:
                existing_pages[page_name] = f.read_text(encoding="utf-8")[:3000]  # 每个页面最多取3000字
            except:
                pass
    
    existing_context = ""
    if existing_pages:
        existing_context = "\n\n## 已有相关页面（供参考，请在此基础上补充）：\n"
        for name, content in existing_pages.items():
            existing_context += f"\n### {name}.md\n{content}\n"
    
    total_chars = len(raw_content)
    print(f"[compiler] 待编译内容：{total_chars} 字符 (~{total_chars//1000}K tokens)")
    
    if total_chars > 400000:
        print("[compiler] ⚠️  内容过长，可能超出 Kimi 上下文窗口")
    
    # 调用 LLM（带重试）
    print(f"[compiler] 调用 {LLM_MODEL} 编译中...")
    prompt = COMPILATION_PROMPT.format(
        raw_content=raw_content,
        existing_context=existing_context
    )
    
    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    
    # 自动重试机制（应对 429 错误）
    import time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=max_tokens
            )
            break  # 成功则跳出
        except Exception as e:
            if "429" in str(e) or "overloaded" in str(e):
                wait_time = (attempt + 1) * 10  # 10秒、20秒、30秒
                print(f"[compiler] ⚠️  服务器过载，{wait_time}秒后重试... ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
                if attempt == max_retries - 1:
                    raise  # 最后一次还失败就抛出
            else:
                raise  # 其他错误直接抛出
    
    llm_output = response.choices[0].message.content
    print(f"[compiler] LLM 返回 {len(llm_output)} 字符")
    
    # 解析输出，写入文件
    _parse_and_save(llm_output)
    
    print("[compiler] ✅ 编译完成！请用 Obsidian 打开 wiki/ 目录查看")


# ── 解析 LLM 输出，写入 wiki/ ──────────────────────────────────────
def _parse_and_save(llm_output: str):
    """
    解析格式：
    ===FILE: concepts/xxx.md===
    内容...
    ===FILE: people/yyy.md===
    内容...
    """
    wiki_root = Path(WIKI_DIR)
    
    # 正则匹配文件分隔符
    pattern = r"===FILE:\s*(.+?)\s*===\n(.*?)(?=\n===FILE:|$)"
    matches = re.findall(pattern, llm_output, re.DOTALL)
    
    if not matches:
        print("[compiler] ⚠️  未检测到 ===FILE:=== 分隔符，尝试保存为单文件")
        fallback_path = wiki_root / "compiled_output.md"
        fallback_path.write_text(llm_output, encoding="utf-8")
        print(f"[compiler] 已保存到 {fallback_path}")
        return
    
    saved_count = 0
    for rel_path, content in matches:
        rel_path = rel_path.strip()
        file_path = wiki_root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content.strip(), encoding="utf-8")
        print(f"  ✓ 新建 {rel_path}")
        saved_count += 1

    # 处理 ===UPDATE:=== 标记（追加到已有页面）
    update_pattern = r"===UPDATE:\s*(.+?)\s*===\n(.*?)(?=\n===(?:FILE|UPDATE):|$)"
    update_matches = re.findall(update_pattern, llm_output, re.DOTALL)
    for rel_path, extra_content in update_matches:
        rel_path = rel_path.strip()
        file_path = wiki_root / rel_path
        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            file_path.write_text(existing.rstrip() + "\n\n" + extra_content.strip(), encoding="utf-8")
            print(f"  ↑ 更新 {rel_path}")
        else:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(extra_content.strip(), encoding="utf-8")
            print(f"  ✓ 新建 {rel_path}（UPDATE转新建）")
    
    print(f"[compiler] 共生成 {saved_count} 个 wiki 页面")
    
    # 更新标签索引
    _update_tags_index()
    
    # 每次编译后自动更新 README
    _update_readme()


# ── 更新标签索引 ──────────────────────────────────────────────────
def _update_tags_index():
    """扫描所有 wiki 页面的 frontmatter，提取 tags，生成索引"""
    wiki_root = Path(WIKI_DIR)
    tags_map = {}
    
    for md_file in wiki_root.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        
        content = md_file.read_text(encoding="utf-8")
        # 提取 frontmatter 中的 tags
        match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
        if match:
            fm = match.group(1)
            tags_match = re.search(r'tags:\s*\[(.*?)\]', fm)
            if tags_match:
                tags_str = tags_match.group(1)
                tags = [t.strip(' "\'') for t in tags_str.split(",")]
                for tag in tags:
                    if tag not in tags_map:
                        tags_map[tag] = []
                    tags_map[tag].append(str(md_file.relative_to(wiki_root)))
    
    # 保存到 index/tags.json
    index_path = wiki_root / "index" / "tags.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(tags_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[compiler] 标签索引已更新：{len(tags_map)} 个标签")


# ── 自动更新 README 索引 ──────────────────────────────────────────
def _update_readme():
    """扫描 wiki/ 下所有 .md 文件，自动重新生成 README 索引"""
    wiki_root = Path(WIKI_DIR)
    concepts, people, others = [], [], []

    for md_file in sorted(wiki_root.rglob("*.md")):
        if md_file.name in ("README.md",):
            continue
        # 跳过 index/ 目录下的文件
        if "index" in md_file.parts:
            continue
        # 跳过 outputs/ 目录
        if "outputs" in md_file.parts:
            continue

        name = md_file.stem
        rel = md_file.relative_to(wiki_root)

        if "people" in str(rel):
            people.append(name)
        elif "concepts" in str(rel):
            concepts.append(name)
        else:
            others.append(name)

    lines = ["# 知识库索引\n"]
    if concepts:
        lines.append("## 概念")
        for c in concepts:
            lines.append(f"- [[{c}]]")
        lines.append("")
    if people:
        lines.append("## 人物")
        for p in people:
            lines.append(f"- [[{p}]]")
        lines.append("")
    if others:
        lines.append("## 其他")
        for o in others:
            lines.append(f"- [[{o}]]")
        lines.append("")

    readme_path = wiki_root / "README.md"
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[compiler] README 已自动更新：{len(concepts)} 个概念，{len(people)} 个人物")


# ── CLI 入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    compile_knowledge_base()