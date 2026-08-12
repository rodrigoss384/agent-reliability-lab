import json
import re
import time
import uuid
from threading import Lock
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import REDIS_URL, RETRIEVAL_LIMIT, SESSION_TTL
from app.providers import DependencyUnavailable, fallback_provider, judge, llm_provider, retriever

try:
    import redis as _redis_lib  # noqa: F401
    _has_redis = True
except ImportError:
    _has_redis = False

app = FastAPI(title="RAG PII Guardrails API", version="0.1.0")

session_locks: dict[str, Lock] = {}

_redis: Any = None
_memory_store: dict[str, dict] = {}


def _get_redis() -> Any:
    global _redis
    if not _has_redis:
        return None
    if _redis is not None:
        return _redis
    try:
        import redis as _r
        _redis = _r.from_url(REDIS_URL, decode_responses=True)
        _redis.ping()
        return _redis
    except Exception:  # noqa: BLE001
        return None
        return None
        return None


def _load_session(session_id: str) -> dict | None:
    try:
        r = _get_redis()
        if r:
            raw = r.get(_session_key(session_id))
            if raw:
                return json.loads(raw)
    except Exception:  # noqa: BLE001
        _redis = None
    return _memory_store.get(session_id)


def _save_session(session_id: str, data: dict) -> None:
    try:
        r = _get_redis()
        if r:
            serialized = json.dumps(data, default=str)
            r.setex(_session_key(session_id), SESSION_TTL, serialized)
            return
    except Exception:  # noqa: BLE001
        _redis = None
    _memory_store[session_id] = data


def _delete_session(session_id: str) -> None:
    try:
        r = _get_redis()
        if r:
            r.delete(_session_key(session_id))
    except Exception:  # noqa: BLE001
        _redis = None
    _memory_store.pop(session_id, None)


def _session_key(session_id: str) -> str:
    return f"rag:session:{session_id}"


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = Field(None, min_length=1)


class Trace(BaseModel):
    retrieved_count: int
    used_count: int
    blocked_count: int
    guardrail_state: str
    total_ms: int
    sources: list[str]


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    model_used: str
    guardrail_state: str
    trace: Trace


def is_sensitive(content: str) -> bool:
    if re.search(r"R\$\s*\d+", content):
        return True
    if re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", content):
        return True
    if re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", content):
        return True
    return bool(re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", content))


@app.post("/api/chat")
def create_chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    lock = session_locks.setdefault(session_id, Lock())
    if not lock.acquire(blocking=False):
        return JSONResponse(
            status_code=409,
            content={"detail": "session_busy", "session_id": session_id}
        )

    try:
        start_time = time.perf_counter()
        now = time.time()
        existing = _load_session(session_id) if request.session_id else None
        if request.session_id and existing:
            data = existing
            data["last_activity"] = now
        else:
            data = {
                "session_id": session_id,
                "created_at": now,
                "last_activity": now,
                "turns": [],
            }

        model_used = llm_provider.model
        used_chunks: list[dict] = []
        retrieved_count = 0
        used_count = 0
        blocked_count = 0
        guardrail_state = "falha-segura"
        answer = ""

        try:
            chunks = retriever.retrieve(request.question, limit=RETRIEVAL_LIMIT)
            retrieved_count = len(chunks)

            for chunk in chunks:
                if is_sensitive(chunk.get("content", "")):
                    blocked_count += 1
                else:
                    used_chunks.append(chunk)

            used_count = len(used_chunks)

            if retrieved_count > 0 and used_count == 0:
                guardrail_state = "bloqueado-na-entrada"
                answer = "Desculpe, o conteudo necessario para responder foi bloqueado por conter dados sensiveis."
            else:
                context = "\n".join([chunk["content"] for chunk in used_chunks])
                prompt = f"Question: {request.question}\nContext: {context}"
                try:
                    candidate = llm_provider.generate(prompt)
                    model_used = llm_provider.model
                except Exception:  # noqa: BLE001
                    candidate = fallback_provider.generate(prompt)
                    model_used = fallback_provider.model
                if is_sensitive(candidate):
                    guardrail_state = "bloqueado-na-saida"
                    answer = "Desculpe, a resposta gerada foi bloqueada por conter dados sensiveis."
                else:
                    try:
                        judge_result = judge.evaluate(candidate)
                    except Exception:  # noqa: BLE001
                        guardrail_state = "falha-segura"
                        answer = "Desculpe, ocorreu uma falha na verificacao da resposta."
                    else:
                        if judge_result == "SIM":
                            guardrail_state = "bloqueado-na-saida"
                            answer = "Desculpe, a resposta gerada foi bloqueada por conter dados sensiveis."
                        elif judge_result == "NAO":
                            guardrail_state = "entregue"
                            answer = candidate
                        else:
                            guardrail_state = "falha-segura"
                            answer = "Desculpe, ocorreu uma falha na verificacao da resposta."
        except DependencyUnavailable:
            answer = "Desculpe, ocorreu uma falha inesperada no pipeline."
            total_ms = int((time.perf_counter() - start_time) * 1000)
            trace = Trace(
                retrieved_count=0,
                used_count=0,
                blocked_count=0,
                guardrail_state=guardrail_state,
                total_ms=total_ms,
                sources=[]
            )
            turn = {
                "question": request.question,
                "answer": answer,
                "model_used": model_used,
                "guardrail_state": guardrail_state,
                "trace": trace.model_dump(),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            data["turns"].append(turn)
            _save_session(session_id, data)
            return JSONResponse(
                status_code=503,
                content=ChatResponse(
                    session_id=session_id,
                    answer=answer,
                    model_used=model_used,
                    guardrail_state=guardrail_state,
                    trace=trace
                ).model_dump()
            )
        except Exception:  # noqa: BLE001
            guardrail_state = "falha-segura"
            answer = "Desculpe, ocorreu uma falha inesperada no pipeline."
            retrieved_count = 0
            used_count = 0
            blocked_count = 0

        total_ms = int((time.perf_counter() - start_time) * 1000)

        trace = Trace(
            retrieved_count=retrieved_count,
            used_count=used_count,
            blocked_count=blocked_count,
            guardrail_state=guardrail_state,
            total_ms=total_ms,
            sources=[chunk.get("source", "unknown") for chunk in used_chunks]
        )

        response = ChatResponse(
            session_id=session_id,
            answer=answer,
            model_used=model_used,
            guardrail_state=guardrail_state,
            trace=trace
        )

        turn = {
            "question": request.question,
            "answer": answer,
            "model_used": model_used,
            "guardrail_state": guardrail_state,
            "trace": trace.model_dump(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        data["turns"].append(turn)
        data["last_activity"] = time.time()
        _save_session(session_id, data)

        return response
    finally:
        lock.release()


@app.get("/api/health")
def get_health():
    try:
        retriever.retrieve("__health_check__", limit=1)
        r = _get_redis()
        redis_ok = r is not None and r.ping()
        return {"status": "healthy", "components": {"database": "available", "redis": "available" if redis_ok else "unavailable"}}
    except Exception:  # noqa: BLE001
        return {"status": "unhealthy", "components": {"database": "unavailable", "redis": "unavailable"}}


@app.get("/api/models")
def get_models():
    return {"primary_model": llm_provider.model, "fallback_model": fallback_provider.model}


@app.get("/api/conversation/{session_id}")
def get_conversation(session_id: str):
    data = _load_session(session_id)
    if not data:
        return JSONResponse(status_code=404, content={"detail": "Sessao nao encontrada"})
    age = time.time() - data.get("last_activity", data["created_at"])
    if age > SESSION_TTL:
        _delete_session(session_id)
        return JSONResponse(status_code=404, content={"detail": "Sessao expirada"})
    return {
        "session_id": data["session_id"],
        "created_at": data["created_at"],
        "turns": [
            {
                "question": t["question"],
                "answer": t["answer"],
                "model_used": t["model_used"],
                "guardrail_state": t["guardrail_state"],
                "trace": t["trace"],
                "timestamp": t["timestamp"]
            }
            for t in data["turns"]
            if t.get("guardrail_state") == "entregue"
        ]
    }
