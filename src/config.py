import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# 配置：LLM API Key 等
LLM_API_KEY = os.getenv("KIMI_API_KEY", "")
LLM_MODEL = "moonshot-v1-128k"  # Kimi 128K 长上下文模型
LLM_BASE_URL = "https://api.moonshot.cn/v1"

WIKI_DIR = "wiki/"
RAW_DIR = "raw/"
OUTPUTS_DIR = "outputs/"
