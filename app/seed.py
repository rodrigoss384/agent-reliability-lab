"""Populate knowledge_documents with embeddings via NVIDIA NIM.

Usage: uv run python -m app.seed
"""
import time
import uuid

import httpx
from sqlalchemy import text

from app.config import (
    NVIDIA_NIM_API_KEY,
    NVIDIA_NIM_BASE_URL,
    NVIDIA_NIM_EMBEDDING_DIM,
    NVIDIA_NIM_EMBEDDING_MODEL,
    OPENROUTER_TIMEOUT,
)
from app.db import engine
from app.models import Base, KnowledgeDocument
from app.providers import KNOWLEDGE_BASE

SEED_RETRIES = 3
SEED_RETRY_DELAY = 2


def get_embedding(text_str: str) -> list[float]:
    if not NVIDIA_NIM_API_KEY:
        raise RuntimeError("NVIDIA_NIM_API_KEY nao configurada")
    last_err: Exception | None = None
    for attempt in range(1, SEED_RETRIES + 1):
        try:
            response = httpx.post(
                f"{NVIDIA_NIM_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {NVIDIA_NIM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": NVIDIA_NIM_EMBEDDING_MODEL,
                    "input": [text_str],
                    "encoding_format": "float",
                    "input_type": "passage",
                    "truncate": "END",
                },
                timeout=OPENROUTER_TIMEOUT,
            )
            response.raise_for_status()
            embedding = response.json()["data"][0]["embedding"]
            if len(embedding) != NVIDIA_NIM_EMBEDDING_DIM:
                raise RuntimeError(
                    f"NVIDIA NIM embedding returned {len(embedding)} dims; expected {NVIDIA_NIM_EMBEDDING_DIM}"
                )
            return embedding
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < SEED_RETRIES:
                time.sleep(SEED_RETRY_DELAY * attempt)
    if last_err is None:
        raise RuntimeError("seed embedding failed without exception")
    raise last_err


def seed() -> None:
    if not NVIDIA_NIM_API_KEY:
        raise RuntimeError("NVIDIA_NIM_API_KEY nao configurada")

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        rows = list(conn.execute(KnowledgeDocument.__table__.select()))
        if rows:
            print(f"[seed] Tabela ja contem {len(rows)} documentos — pulando.")
            return

    print(f"[seed] Gerando embeddings via NVIDIA NIM ({NVIDIA_NIM_EMBEDDING_MODEL})...")

    with engine.begin() as conn:
        for i, doc in enumerate(KNOWLEDGE_BASE):
            embedding = get_embedding(doc["content"])
            conn.execute(
                KnowledgeDocument.__table__.insert().values(
                    id=uuid.uuid4(),
                    source=doc["source"],
                    content=doc["content"],
                    embedding=embedding,
                    preco_publico=bool(doc.get("preco_publico", False)),
                )
            )
            flag_marker = " *preco_publico" if doc.get("preco_publico") else ""
            print(f"  [{i + 1}/{len(KNOWLEDGE_BASE)}]{flag_marker} {doc['source']} (dim={len(embedding)})")


def apply_metadata_flags() -> None:
    """Atualiza metadata na tabela sem regenerar embeddings.

    Necessario quando KNOWLEDGE_BASE ganha campos novos (ex.: preco_publico) e os
    documentos ja existem no banco. Idempotente: apenas UPDATE nas linhas afetadas.
    """
    with engine.begin() as conn:
        for doc in KNOWLEDGE_BASE:
            flag = bool(doc.get("preco_publico", False))
            conn.execute(
                text("UPDATE knowledge_documents SET preco_publico = :flag WHERE content = :content"),
                {"flag": flag, "content": doc["content"]},
            )
    print("[seed] apply_metadata_flags: preco_publico sincronizado em knowledge_documents.")

    with engine.connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM knowledge_documents")).scalar()
        print(f"[seed] concluido. knowledge_documents: {cnt} linhas.")


if __name__ == "__main__":
    seed()
