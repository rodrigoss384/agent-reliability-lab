"""Populate knowledge_documents with embeddings via OpenRouter.

Usage: uv run python -m app.seed
"""
import time
import uuid

import httpx

from app.config import (
    OPENROUTER_BASE_URL,
    OPENROUTER_EMBEDDING_MODEL,
    OPENROUTER_KEY,
    OPENROUTER_TIMEOUT,
)
from app.db import engine
from app.models import Base, KnowledgeDocument
from app.providers import KNOWLEDGE_BASE

SEED_RETRIES = 3
SEED_RETRY_DELAY = 2


def get_embedding(text: str) -> list[float]:
    last_err = None
    for attempt in range(1, SEED_RETRIES + 1):
        try:
            response = httpx.post(
                f"{OPENROUTER_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": OPENROUTER_EMBEDDING_MODEL, "input": text},
                timeout=OPENROUTER_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < SEED_RETRIES:
                time.sleep(SEED_RETRY_DELAY * attempt)
    raise last_err  # type: ignore[misc]


def seed() -> None:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY nao configurada")

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        result = conn.execute(KnowledgeDocument.__table__.select())
        if result.first():
            count = len(result.all())
            print(f"[seed] Tabela ja contem {count} documentos — pulando.")
            return

    print(f"[seed] Gerando embeddings para {len(KNOWLEDGE_BASE)} documentos...")

    with engine.begin() as conn:
        for i, doc in enumerate(KNOWLEDGE_BASE):
            embedding = get_embedding(doc["content"])
            conn.execute(
                KnowledgeDocument.__table__.insert().values(
                    id=uuid.uuid4(),
                    source=doc["source"],
                    content=doc["content"],
                    embedding=embedding,
                )
            )
            print(f"  [{i + 1}/{len(KNOWLEDGE_BASE)}] {doc['source']}")

    print("[seed] concluido.")


if __name__ == "__main__":
    seed()
