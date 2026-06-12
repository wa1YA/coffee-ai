"""
配置管理：从环境变量读取所有配置，绝不硬编码密钥
"""
import os

# 尝试加载 .env 文件（本地开发用，生产环境直接用系统环境变量）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 生产环境不需要 dotenv


class Config:
    # LLM
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    # HuggingFace 镜像（国内加速）
    HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
