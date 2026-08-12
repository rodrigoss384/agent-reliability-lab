import os
from pathlib import Path

from dotenv import load_dotenv

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://rag:rag@localhost:5432/rag_guardrails")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_TIMEOUT = _float("OPENROUTER_TIMEOUT", 30)
OPENROUTER_PRIMARY_MODEL = os.getenv("OPENROUTER_PRIMARY_MODEL", "google/gemini-2.0-flash-001")
OPENROUTER_FALLBACK_MODEL = os.getenv("OPENROUTER_FALLBACK_MODEL", "meta-llama/llama-3.2-3b-instruct:free")
OPENROUTER_JUDGE_MODEL = os.getenv("OPENROUTER_JUDGE_MODEL", "deepseek/deepseek-chat-v3-0324:free")
OPENROUTER_EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small")
OPENROUTER_TEMPERATURE = _float("OPENROUTER_TEMPERATURE", 0.7)
OPENROUTER_FALLBACK_TEMPERATURE = _float("OPENROUTER_FALLBACK_TEMPERATURE", 0.5)
OPENROUTER_JUDGE_TEMPERATURE = _float("OPENROUTER_JUDGE_TEMPERATURE", 0.1)

SESSION_TTL = _int("SESSION_TTL", 86400)
RETRIEVAL_LIMIT = _int("RETRIEVAL_LIMIT", 5)
