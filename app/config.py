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


def _bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes", "on")


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://rag:rag@localhost:5432/rag_guardrails"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_TIMEOUT = _float("OPENROUTER_TIMEOUT", 30)
OPENROUTER_PRIMARY_MODEL = os.getenv("OPENROUTER_PRIMARY_MODEL", "google/gemini-2.0-flash-001")
OPENROUTER_TEMPERATURE = _float("OPENROUTER_TEMPERATURE", 0.7)
OPENROUTER_REASONING_ENABLED = _bool("OPENROUTER_REASONING_ENABLED", True)

NVIDIA_NIM_BASE_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_NIM_API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "")
NVIDIA_NIM_FALLBACK_MODEL = os.getenv("NVIDIA_NIM_FALLBACK_MODEL", "meta/llama-3.1-8b-instruct")
NVIDIA_NIM_TEMPERATURE = _float("NVIDIA_NIM_TEMPERATURE", 0.5)

NVIDIA_NIM_JUDGE_MODEL = os.getenv("NVIDIA_NIM_JUDGE_MODEL", "meta/llama-3.1-8b-instruct")
NVIDIA_NIM_JUDGE_TEMPERATURE = _float("NVIDIA_NIM_JUDGE_TEMPERATURE", 0.1)

NVIDIA_NIM_EMBEDDING_MODEL = os.getenv("NVIDIA_NIM_EMBEDDING_MODEL", "nvidia/nemotron-3-embed-1b")
NVIDIA_NIM_EMBEDDING_DIM = _int("NVIDIA_NIM_EMBEDDING_DIM", 2048)

SESSION_TTL = _int("SESSION_TTL", 86400)
RETRIEVAL_LIMIT = _int("RETRIEVAL_LIMIT", 5)
