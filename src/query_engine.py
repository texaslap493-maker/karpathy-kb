"""
Stage 4: Query Engine — 长上下文问答引擎
将整个 wiki/ 加载为上下文，支持多轮对话，回答引用文件来源
"""

import glob
import json
from pathlib import Path
from openai import OpenAI

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, WIKI_DIR, OUTPUTS_DIR


SYSTEM_PROMPT = """你是一个基于个人知识库的AI助手。
你拥有以下知识库的全部内容（由用户整理的Markdown文件组成）。
请仅基于这些材料回答问题，如果知识库中没有相关信息，请明确说明。
回答时引用具体文件来源（格式：来源：xxx.md）。"""


class KarpathyKnowledgeBase:
    def __init__(self, resume_from: str = None):
        self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self.chat_history = []
        self.session_file = resume_from  # 记住是从哪个文件加载的
        print("[query] 加载 wiki 知识库...")
        self.context = self._load_wiki()
        print(f"[query] 知识库加载完成，共 {len(self.context)} 字符")

    def _load_wiki(self) -> str:
        """一次性加载整个 wiki/ 作为上下文"""
        wiki_files = sorted(Path(WIKI_DIR).rglob("*.md"))
        parts = []
        for f in wiki_files:
            try:
                content = f.read_text(encoding="utf-8")
                parts.append(f"\n---\nFILE: {f}\n---\n{content}")
            except Exception as e:
                print(f"[query] 跳过 {f}: {e}")
        return "\n".join(parts)

    def query(self, question: str) -> str:
        """多轮对话问答，保留历史"""
        # 构建消息列表
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n知识库内容：\n" + self.context}
        ]
        messages.extend(self.chat_history)
        messages.append({"role": "user", "content": question})

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=4000
        )
        answer = response.choices[0].message.content

        # 保存到对话历史
        self.chat_history.append({"role": "user", "content": question})
        self.chat_history.append({"role": "assistant", "content": answer})

        return answer

    def save_session(self):
        """保存对话历史到 outputs/sessions/"""
        if not self.chat_history:
            return
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 保存 JSON 对话记录到 outputs/sessions/
        if self.session_file:
            json_path = Path(OUTPUTS_DIR) / "sessions" / self.session_file
            print(f"[query] 覆盖原对话文件：{json_path}")
        else:
            out_dir = Path(OUTPUTS_DIR) / "sessions"
            out_dir.mkdir(parents=True, exist_ok=True)
            json_path = out_dir / f"session_{timestamp}.json"
            self.session_file = json_path.name
            print(f"[query] 对话记录已保存：{json_path}")
        
        json_path.write_text(
            json.dumps(self.chat_history, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def generate_wiki_page(self):
        """智能生成 wiki 页面（知识库自我增强）"""
        if not self.chat_history:
            print("[query] 没有对话历史，无法生成 wiki 页面")
            return
        
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        print("[query] 正在分析对话内容，生成结构化知识...")
        self._intelligent_wiki_generation(timestamp)

    def _intelligent_wiki_generation(self, timestamp: str):
        """
        智能问答归档：
        1. LLM 分析对话，提取核心概念、关键洞察
        2. 生成有意义的标题和摘要
        3. 自动添加 [[双向链接]] 到现有概念
        4. 决定是创建新页面还是补充到现有页面
        """
        # 构建对话文本
        conversation = "\n\n".join([
            f"{'用户' if msg['role'] == 'user' else 'AI'}：{msg['content']}"
            for msg in self.chat_history
        ])
        
        # 获取现有概念列表（用于链接生成）
        existing_concepts = self._get_existing_concepts()
        
        analysis_prompt = f"""你是知识库管理助手。请分析以下对话，决定如何将其整合到知识库中。

## 现有知识库概念
{', '.join(existing_concepts[:50])}  # 限制长度避免超token

## 对话内容
{conversation}

## 任务要求
请以 JSON 格式输出分析结果：

```json
{{
  "action": "create_new | update_existing | skip",
  "reason": "为什么选择这个操作",
  "title": "如果创建新页面，给出简洁有意义的标题（不要包含'问答记录'等字样）",
  "target_file": "如果是 update_existing，指定要更新的文件名（如'深度学习.md'）",
  "summary": "一句话总结对话的核心价值",
  "key_insights": ["洞察1", "洞察2"],
  "related_concepts": ["概念1", "概念2"],  // 从现有概念中选择相关的
  "tags": ["标签1", "标签2"]
}}
```

**判断标准**：
- 如果对话只是简单查询现有知识，选择 skip
- 如果对话产生了新的理解、综合了跨概念的洞察，选择 create_new
- 如果对话深化了某个现有概念的理解，选择 update_existing
- 标题要体现内容本质，如"Transformer与RNN的性能对比"而非"问答记录"
"""

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": analysis_prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            
            # 解析 JSON 响应
            result_text = response.choices[0].message.content
            # 提取 JSON（可能被包裹在 ```json ``` 中）
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group(1)
            
            analysis = json.loads(result_text)
            
            # 根据分析结果执行操作
            if analysis["action"] == "skip":
                print(f"[query] 跳过归档：{analysis['reason']}")
                return
            
            elif analysis["action"] == "create_new":
                self._create_new_wiki_page(analysis, timestamp)
            
            elif analysis["action"] == "update_existing":
                self._update_existing_wiki_page(analysis, timestamp)
                
        except Exception as e:
            print(f"[query] ❌ 智能分析失败：{e}")
            print(f"[query] 对话已保存到 JSON，你可以稍后重试生成 wiki 页面")

    def _get_existing_concepts(self) -> list:
        """获取现有 wiki 中的所有概念名称"""
        concepts = []
        for f in Path(WIKI_DIR).rglob("*.md"):
            if f.stem not in ["README", "compile_state", "lint_report", "tags"]:
                concepts.append(f.stem)
        return concepts

    def _create_new_wiki_page(self, analysis: dict, timestamp: str):
        """创建新的知识页面"""
        from datetime import datetime
        
        title = analysis["title"]
        filename = title.replace(" ", "_").replace("/", "_") + ".md"
        wiki_path = Path(WIKI_DIR) / "insights" / filename
        wiki_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 构建双向链接
        related_links = " ".join([f"[[{c}]]" for c in analysis.get("related_concepts", [])])
        
        content = f"""---
title: "{title}"
date: {datetime.now().strftime('%Y-%m-%d')}
tags: {json.dumps(analysis.get('tags', ['问答洞察']), ensure_ascii=False)}
source: "对话归档 {timestamp}"
---

# {title}

## 摘要
{analysis['summary']}

## 核心洞察
"""
        for insight in analysis.get("key_insights", []):
            content += f"- {insight}\n"
        
        content += f"\n## 详细内容\n"
        for msg in self.chat_history:
            if msg["role"] == "user":
                content += f"\n**问：** {msg['content']}\n"
            else:
                content += f"\n{msg['content']}\n"
        
        content += f"\n## 相关概念\n{related_links}\n"
        
        wiki_path.write_text(content, encoding="utf-8")
        print(f"[query] ✅ 新知识页面已创建：{wiki_path}")
        print(f"       标题：{title}")
        print(f"       关联概念：{', '.join(analysis.get('related_concepts', []))}")

    def _update_existing_wiki_page(self, analysis: dict, timestamp: str):
        """在现有页面中追加新内容"""
        from datetime import datetime
        
        target_file = analysis["target_file"]
        wiki_path = Path(WIKI_DIR) / "concepts" / target_file
        
        if not wiki_path.exists():
            print(f"[query] ⚠️  目标文件不存在，改为创建新页面")
            self._create_new_wiki_page(analysis, timestamp)
            return
        
        # 读取现有内容
        existing = wiki_path.read_text(encoding="utf-8")
        
        # 追加新的讨论部分
        addition = f"""

---
## 补充讨论（{datetime.now().strftime('%Y-%m-%d')}）

### {analysis['summary']}

"""
        for msg in self.chat_history[-4:]:  # 只保留最后2轮对话
            if msg["role"] == "user":
                addition += f"**问：** {msg['content']}\n\n"
            else:
                addition += f"{msg['content']}\n\n"
        
        wiki_path.write_text(existing + addition, encoding="utf-8")
        print(f"[query] ✅ 已更新现有页面：{wiki_path}")
        print(f"       新增内容：{analysis['summary']}")


    def clear_history(self):
        self.chat_history = []
        print("[query] 对话历史已清空")


# ── CLI 入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    kb = KarpathyKnowledgeBase()
    print("\n知识库已就绪！输入问题开始问答，输入 'save' 保存对话，'clear' 清空历史，'q' 退出\n")

    while True:
        user_input = input("你：").strip()
        if not user_input:
            continue
        if user_input.lower() == "q":
            save_wiki = input("退出前是否保存为新 wiki 页面？(y/n): ").strip().lower() == "y"
            kb.save_session(save_wiki=save_wiki)
            break
        elif user_input.lower() == "save":
            save_wiki = input("是否同时保存为新 wiki 页面？(y/n): ").strip().lower() == "y"
            kb.save_session(save_wiki=save_wiki)
        elif user_input.lower() == "clear":
            kb.clear_history()
        else:
            answer = kb.query(user_input)
            print(f"\nAI：{answer}\n")
