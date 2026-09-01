import json
import time
import uuid
from threading import Lock
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langfuse import get_client, observe
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import REDIS_URL, RETRIEVAL_LIMIT, SESSION_TTL
from app.db import engine
from app.providers import (
    AGENT_SYSTEM_PROMPT,
    EMBEDDING_PROVIDER_NAME,
    DependencyUnavailable,
    RateLimitError,
    classify_pii,
    is_sensitive,
    judge,
    llm_provider,
    nvidia_nim_embedding_provider,
    nvidia_nim_fallback_provider,
    retriever,
)

try:
    import redis as _redis_lib  # noqa: F401

    _has_redis = True
except ImportError:
    _has_redis = False

app = FastAPI(title="RAG PII Guardrails API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_locks: dict[str, Lock] = {}


@app.on_event("shutdown")
def shutdown_event():
    try:
        get_client().flush()
    except Exception:  # noqa: BLE001, S110
        pass


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


def _summarize_embedding(vec: list[float] | None) -> dict[str, Any]:
    if not vec:
        return {
            "dim": 0,
            "l2_norm": 0.0,
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "first5": [],
            "last5": [],
        }
    n = len(vec)
    total = sum(vec)
    mn = min(vec)
    mx = max(vec)
    norm = sum(v * v for v in vec) ** 0.5
    return {
        "dim": n,
        "l2_norm": round(norm, 6),
        "min": round(mn, 6),
        "max": round(mx, 6),
        "mean": round(total / n, 6),
        "first5": [round(v, 6) for v in vec[:5]],
        "last5": [round(v, 6) for v in vec[-5:]],
    }


def _generate_with_fallbacks(
    messages: list[dict[str, Any]],
    primary_model: str,
    fallback_model: str,
    fallback_used_init: bool,
) -> tuple[str, list | None, str, bool]:
    candidate: str = ""
    reasoning_details: list | None = None
    model_used = primary_model
    fallback_used = fallback_used_init

    providers_chain: list[tuple[Any, str, bool]] = [
        (llm_provider, primary_model, False),
    ]
    if nvidia_nim_fallback_provider is not None:
        providers_chain.append((nvidia_nim_fallback_provider, fallback_model, True))

    assert len(providers_chain) == 2, (
        f"Chat chain deve ter exatamente 2 provedores; encontrou {len(providers_chain)}"
    )

    last_exc: Exception | None = None
    last_rate_limit: RateLimitError | None = None
    for provider, model_name, is_fallback in providers_chain:
        try:
            candidate, reasoning_details = provider.generate(messages=messages)
            model_used = model_name
            fallback_used = is_fallback
            return candidate, reasoning_details, model_used, fallback_used
        except RateLimitError as rl_exc:
            last_rate_limit = rl_exc
            last_exc = None
            continue
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue

    if last_rate_limit is not None:
        raise last_rate_limit
    if last_exc is not None:
        raise last_exc
    raise RateLimitError(
        message="All providers exhausted",
        provider="multi-provider",
        retry_after=None,
    )


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
    rag_used: bool = False
    input_pii_detected: bool = False
    input_pii_categories: list[str] = Field(
        default_factory=list,
        description="Categorias PII detectadas no input do usuario (bloqueio duro antes do pipeline).",
    )
    pii_categories: list[str] = Field(
        default_factory=list,
        description="Categorias PII que afetaram a decisao final (resposta do LLM). Inclui sentinela judge_block quando judge detecta sem regex.",
    )
    pii_categories_retrieval: list[str] = Field(
        default_factory=list,
        description="Categorias PII detectadas em chunks do retrieval (informativo; nao afeta decisao).",
    )
    judge_decision: str = ""
    judge_model: str = ""
    primary_model: str = ""
    fallback_used: bool = False
    pre_guardrail_ms: int = 0
    llm_ms: int = 0
    post_guardrail_ms: int = 0
    pii_regex_ms: int = 0
    pii_judge_ms: int = 0
    rate_limit_reason: str = ""
    embedding_provider: str = EMBEDDING_PROVIDER_NAME
    intent_skipped_retrieval: bool = False


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    model_used: str
    guardrail_state: str
    trace: Trace


@app.post("/api/chat")
@observe(name="chat_pipeline", capture_input=False, capture_output=False)
def create_chat(request: ChatRequest):
    client = get_client()
    session_id = request.session_id or str(uuid.uuid4())

    try:
        input_sensitive = is_sensitive(request.question)
    except Exception:  # noqa: BLE001
        trace = Trace(
            retrieved_count=0,
            used_count=0,
            blocked_count=0,
            guardrail_state="falha-segura",
            total_ms=0,
            sources=[],
            rag_used=False,
            input_pii_detected=False,
            judge_decision="",
            judge_model=judge.model,
            primary_model=llm_provider.model,
            fallback_used=False,
        )
        client.update_current_span(
            metadata={"guardrail_state": "falha-segura", "pii_categories": []}
        )
        return ChatResponse(
            session_id=session_id,
            answer="Desculpe, ocorreu uma falha inesperada no pipeline.",
            model_used=llm_provider.model,
            guardrail_state="falha-segura",
            trace=trace,
        )

    if input_sensitive:
        now = time.time()
        data = _load_session(session_id) or {
            "session_id": session_id,
            "created_at": now,
            "last_activity": now,
            "turns": [],
        }
        data["last_activity"] = now
        input_categories = classify_pii(request.question)
        trace = Trace(
            retrieved_count=0,
            used_count=0,
            blocked_count=0,
            guardrail_state="bloqueado-na-entrada",
            total_ms=0,
            sources=[],
            rag_used=False,
            input_pii_detected=True,
            input_pii_categories=input_categories,
            judge_decision="",
            judge_model=judge.model,
            primary_model=llm_provider.model,
            fallback_used=False,
        )
        answer = (
            "Detectei dados sensiveis (PII) na sua pergunta. "
            "Por politicas de privacidade, nao posso processar essa solicitacao."
        )
        turn = {
            "question": request.question,
            "answer": answer,
            "model_used": llm_provider.model,
            "guardrail_state": "bloqueado-na-entrada",
            "trace": trace.model_dump(),
            "reasoning_details": None,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        data["turns"].append(turn)
        _save_session(session_id, data)
        client.update_current_span(
            metadata={"guardrail_state": "bloqueado-na-entrada", "pii_categories": input_categories}
        )
        return ChatResponse(
            session_id=session_id,
            answer=answer,
            model_used=llm_provider.model,
            guardrail_state="bloqueado-na-entrada",
            trace=trace,
        )

    lock = session_locks.setdefault(session_id, Lock())
    if not lock.acquire(blocking=False):
        return JSONResponse(
            status_code=409, content={"detail": "session_busy", "session_id": session_id}
        )

    try:
        start_time = time.perf_counter()
        pre_guardrail_start = start_time
        llm_start = start_time
        post_guardrail_start = start_time
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

        primary_model = llm_provider.model
        fallback_model = nvidia_nim_fallback_provider.model if nvidia_nim_fallback_provider else ""
        model_used = primary_model
        fallback_used = False
        used_chunks: list[dict] = []
        retrieved_count = 0
        used_count = 0
        blocked_count = 0
        guardrail_state = "falha-segura"
        answer = ""
        reasoning_details: list | None = None
        pii_categories: list[str] = []
        pii_categories_retrieval: list[str] = []
        judge_decision: str = ""
        pre_guardrail_ms = 0
        llm_ms = 0
        post_guardrail_ms = 0
        pii_regex_ms = 0
        pii_judge_ms = 0
        intent_skipped_retrieval = False
        from app.providers import _is_obvious_non_question, intent_classifier

        try:
            needs_retrieval = not _is_obvious_non_question(request.question)
            if needs_retrieval:
                try:
                    needs_retrieval = intent_classifier.classify(request.question)
                except Exception:  # noqa: BLE001
                    needs_retrieval = True
            intent_skipped_retrieval = not needs_retrieval

            if needs_retrieval:
                chunks = retriever.retrieve(request.question, limit=RETRIEVAL_LIMIT)
                retrieved_count = len(chunks)

                for chunk in chunks:
                    is_pub = bool(chunk.get("preco_publico"))
                    if is_sensitive(chunk.get("content", ""), preco_publico=is_pub):
                        blocked_count += 1
                        pii_categories_retrieval = list(
                            {
                                *pii_categories_retrieval,
                                *classify_pii(chunk.get("content", ""), preco_publico=is_pub),
                            }
                        )
                    else:
                        used_chunks.append(chunk)

                used_count = len(used_chunks)
            pre_guardrail_ms = int((time.perf_counter() - pre_guardrail_start) * 1000)

            if retrieved_count > 0 and used_count == 0:
                guardrail_state = "bloqueado-na-entrada"
                answer = "Desculpe, o conteudo necessario para responder foi bloqueado por conter dados sensiveis."
            else:
                conversation_messages: list[dict[str, Any]] = [
                    {"role": "system", "content": AGENT_SYSTEM_PROMPT}
                ]
                for prev_turn in data.get("turns", []):
                    if prev_turn.get("guardrail_state") == "entregue":
                        conversation_messages.append(
                            {"role": "user", "content": prev_turn["question"]}
                        )
                        assistant_msg: dict[str, Any] = {
                            "role": "assistant",
                            "content": prev_turn["answer"],
                        }
                        if prev_turn.get("reasoning_details") is not None:
                            assistant_msg["reasoning_details"] = prev_turn["reasoning_details"]
                        conversation_messages.append(assistant_msg)

                if used_count > 0:
                    context = "\n".join([chunk["content"] for chunk in used_chunks])
                    conversation_messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Contexto da base de conhecimento:\n{context}\n\n"
                                f"Pergunta: {request.question}"
                            ),
                        }
                    )
                else:
                    conversation_messages.append({"role": "user", "content": request.question})

                llm_start = time.perf_counter()
                candidate, reasoning_details, model_used, fallback_used = _generate_with_fallbacks(
                    conversation_messages,
                    primary_model,
                    fallback_model,
                    fallback_used,
                )
                llm_ms = int((time.perf_counter() - llm_start) * 1000)

                has_preco_publico_chunk = any(bool(c.get("preco_publico")) for c in used_chunks)

                post_guardrail_start = time.perf_counter()
                regex_start = time.perf_counter()
                candidate_categories = classify_pii(
                    candidate, preco_publico=has_preco_publico_chunk
                )
                if candidate_categories:
                    pii_categories = list({*pii_categories, *candidate_categories})
                    pii_categories_retrieval = [
                        c for c in pii_categories_retrieval if c not in pii_categories
                    ]
                pii_regex_ms = int((time.perf_counter() - regex_start) * 1000)
                if is_sensitive(candidate, preco_publico=has_preco_publico_chunk):
                    guardrail_state = "bloqueado-na-saida"
                    answer = "Desculpe, a resposta gerada foi bloqueada por conter dados sensiveis."
                else:
                    judge_start = time.perf_counter()
                    if has_preco_publico_chunk and not pii_categories:
                        judge_decision = "NAO"
                        guardrail_state = "entregue"
                        answer = candidate
                    else:
                        try:
                            judge_decision = judge.evaluate(candidate)
                        except Exception:  # noqa: BLE001
                            if is_sensitive(candidate, preco_publico=has_preco_publico_chunk):
                                guardrail_state = "bloqueado-na-saida"
                                answer = "Desculpe, a resposta gerada foi bloqueada por conter dados sensiveis."
                            else:
                                guardrail_state = "entregue"
                                answer = candidate
                        else:
                            if judge_decision == "SIM":
                                guardrail_state = "bloqueado-na-saida"
                                answer = "Desculpe, a resposta gerada foi bloqueada por conter dados sensiveis."
                                if not pii_categories:
                                    pii_categories = ["judge_block"]
                            elif judge_decision == "NAO":
                                guardrail_state = "entregue"
                                answer = candidate
                            else:
                                guardrail_state = "falha-segura"
                                answer = "Desculpe, ocorreu uma falha na verificacao da resposta."
                    pii_judge_ms = int((time.perf_counter() - judge_start) * 1000)
                post_guardrail_ms = int((time.perf_counter() - post_guardrail_start) * 1000)
        except DependencyUnavailable:
            answer = "Desculpe, ocorreu uma falha inesperada no pipeline."
            total_ms = int((time.perf_counter() - start_time) * 1000)
            trace = Trace(
                retrieved_count=0,
                used_count=0,
                blocked_count=0,
                guardrail_state=guardrail_state,
                total_ms=total_ms,
                sources=[],
                rag_used=False,
                pii_categories=pii_categories,
                pii_categories_retrieval=pii_categories_retrieval,
                intent_skipped_retrieval=intent_skipped_retrieval,
                judge_decision=judge_decision,
                judge_model=judge.model,
                primary_model=primary_model,
                fallback_used=fallback_used,
                pre_guardrail_ms=pre_guardrail_ms,
                llm_ms=llm_ms,
                post_guardrail_ms=post_guardrail_ms,
                pii_regex_ms=pii_regex_ms,
                pii_judge_ms=pii_judge_ms,
            )
            turn = {
                "question": request.question,
                "answer": answer,
                "model_used": model_used,
                "guardrail_state": guardrail_state,
                "trace": trace.model_dump(),
                "reasoning_details": None,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            data["turns"].append(turn)
            _save_session(session_id, data)
            client.update_current_span(
                metadata={"guardrail_state": guardrail_state, "pii_categories": pii_categories}
            )
            return JSONResponse(
                status_code=503,
                content=ChatResponse(
                    session_id=session_id,
                    answer=answer,
                    model_used=model_used,
                    guardrail_state=guardrail_state,
                    trace=trace,
                ).model_dump(),
            )
        except RateLimitError as rl_exc:
            guardrail_state = "limite-cota"
            if rl_exc.provider == "openrouter":
                answer = (
                    "Limite diario gratuito do OpenRouter atingido. "
                    "Configure NVIDIA_NIM_API_KEY no .env para o fallback NVIDIA NIM assumir. "
                    "Veja instrucoes em README.md."
                )
            elif rl_exc.provider == "nvidia_nim":
                answer = (
                    "Limite de cota atingido tambem no fallback NVIDIA NIM. "
                    "Verifique seus creditos trial em build.nvidia.com. "
                    "Veja instrucoes em README.md."
                )
            else:
                answer = (
                    "Limite de cota atingido em todos os provedores configurados. "
                    "Veja instrucoes em README.md."
                )
            retrieved_count = 0
            used_chunks = []
            used_count = 0
            blocked_count = 0
            llm_ms = int((time.perf_counter() - llm_start) * 1000)

            total_ms = int((time.perf_counter() - start_time) * 1000)
            trace = Trace(
                retrieved_count=retrieved_count,
                used_count=used_count,
                blocked_count=blocked_count,
                guardrail_state=guardrail_state,
                total_ms=total_ms,
                sources=[],
                rag_used=False,
                pii_categories=pii_categories,
                pii_categories_retrieval=pii_categories_retrieval,
                intent_skipped_retrieval=intent_skipped_retrieval,
                judge_decision=judge_decision,
                judge_model=judge.model,
                primary_model=primary_model,
                fallback_used=fallback_used,
                pre_guardrail_ms=pre_guardrail_ms,
                llm_ms=llm_ms,
                post_guardrail_ms=post_guardrail_ms,
                pii_regex_ms=pii_regex_ms,
                pii_judge_ms=pii_judge_ms,
                rate_limit_reason=rl_exc.message,
            )
            turn = {
                "question": request.question,
                "answer": answer,
                "model_used": model_used,
                "guardrail_state": guardrail_state,
                "trace": trace.model_dump(),
                "reasoning_details": None,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            data["turns"].append(turn)
            _save_session(session_id, data)
            client.update_current_span(
                metadata={"guardrail_state": guardrail_state, "pii_categories": pii_categories}
            )
            return JSONResponse(
                status_code=429,
                content=ChatResponse(
                    session_id=session_id,
                    answer=answer,
                    model_used=model_used,
                    guardrail_state=guardrail_state,
                    trace=trace,
                ).model_dump(),
            )
        except Exception:  # noqa: BLE001
            guardrail_state = "falha-segura"
            answer = "Desculpe, ocorreu uma falha inesperada no pipeline."
            retrieved_count = 0
            used_chunks = []
            used_count = 0
            blocked_count = 0

        total_ms = int((time.perf_counter() - start_time) * 1000)

        trace = Trace(
            retrieved_count=retrieved_count,
            used_count=used_count,
            blocked_count=blocked_count,
            guardrail_state=guardrail_state,
            total_ms=total_ms,
            sources=[chunk.get("source", "unknown") for chunk in used_chunks],
            rag_used=used_count > 0,
            pii_categories=pii_categories,
            pii_categories_retrieval=pii_categories_retrieval,
            intent_skipped_retrieval=intent_skipped_retrieval,
            judge_decision=judge_decision,
            judge_model=judge.model,
            primary_model=primary_model,
            fallback_used=fallback_used,
            pre_guardrail_ms=pre_guardrail_ms,
            llm_ms=llm_ms,
            post_guardrail_ms=post_guardrail_ms,
            pii_regex_ms=pii_regex_ms,
            pii_judge_ms=pii_judge_ms,
        )

        response = ChatResponse(
            session_id=session_id,
            answer=answer,
            model_used=model_used,
            guardrail_state=guardrail_state,
            trace=trace,
        )

        turn = {
            "question": request.question,
            "answer": answer,
            "model_used": model_used,
            "guardrail_state": guardrail_state,
            "trace": trace.model_dump(),
            "reasoning_details": reasoning_details,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        data["turns"].append(turn)
        data["last_activity"] = time.time()
        _save_session(session_id, data)

        has_preco_publico_bypass = False
        if used_chunks:
            has_preco_publico_chunk = any(bool(c.get("preco_publico")) for c in used_chunks)
            has_preco_publico_bypass = has_preco_publico_chunk and not pii_categories

        client.update_current_span(
            metadata={
                "guardrail_state": guardrail_state,
                "pii_categories": pii_categories,
                "preco_publico_bypass": has_preco_publico_bypass,
            }
        )

        return response
    finally:
        lock.release()


@app.get("/api/health")
def get_health():
    db_ok = False
    embedding_ok = False
    try:
        retriever.retrieve("__health_check__", limit=1)
        db_ok = True
        embedding_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
        embedding_ok = False

    r = _get_redis()
    redis_ok = r is not None and r.ping()

    providers = {
        "primary_chat": llm_provider.model,
        "fallback_chat": (
            nvidia_nim_fallback_provider.model if nvidia_nim_fallback_provider else ""
        ),
        "embedding": (nvidia_nim_embedding_provider.model if nvidia_nim_embedding_provider else ""),
        "judge": judge.model,
    }

    status = "healthy" if db_ok and embedding_ok else "unhealthy"
    return {
        "status": status,
        "components": {
            "database": "available" if db_ok else "unavailable",
            "embedding": "available" if embedding_ok else "unavailable",
            "redis": "available" if redis_ok else "unavailable",
        },
        "providers": providers,
    }


@app.get("/api/models")
def get_models():
    fallback_model = nvidia_nim_fallback_provider.model if nvidia_nim_fallback_provider else ""
    return {"primary_model": llm_provider.model, "fallback_model": fallback_model}


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
                "timestamp": t["timestamp"],
            }
            for t in data["turns"]
            if t.get("guardrail_state") == "entregue"
        ],
    }


@app.get("/api/admin/knowledge-documents")
def list_knowledge_documents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source: str | None = Query(None, min_length=1),
):
    """Table Editor (READ-ONLY): lista knowledge_documents com resumo do embedding.

    Endpoint dev-only. Sem autenticacao; ambiente de demonstracao local.
    """
    where_sql = ""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if source:
        where_sql = "WHERE source = :source"
        params["source"] = source

    total_sql = f"SELECT COUNT(*) FROM knowledge_documents {where_sql}"
    rows_sql = (
        f"SELECT id, source, content, embedding::text AS embedding_str, preco_publico, created_at "
        f"FROM knowledge_documents {where_sql} "
        f"ORDER BY created_at ASC, id ASC "
        f"LIMIT :limit OFFSET :offset"
    )

    with engine.connect() as conn:
        total = conn.execute(text(total_sql), params).scalar() or 0
        rows = conn.execute(text(rows_sql), params).fetchall()

    schema = [
        {"name": "id", "type": "uuid", "nullable": False, "primary_key": True},
        {"name": "source", "type": "varchar(255)", "nullable": False, "primary_key": False},
        {"name": "content", "type": "text", "nullable": False, "primary_key": False},
        {"name": "embedding", "type": "vector(2048)", "nullable": True, "primary_key": False},
        {"name": "preco_publico", "type": "boolean", "nullable": False, "primary_key": False},
        {"name": "created_at", "type": "timestamptz", "nullable": False, "primary_key": False},
    ]

    parsed_rows = []
    for r in rows:
        emb_str = r.embedding_str
        vec: list[float] | None = None
        if emb_str:
            stripped = emb_str.strip().lstrip("[").rstrip("]")
            if stripped:
                try:
                    vec = [float(x) for x in stripped.split(",")]
                except ValueError:
                    vec = None
        parsed_rows.append(
            {
                "id": str(r.id),
                "source": r.source,
                "content": r.content,
                "embedding_summary": _summarize_embedding(vec),
                "preco_publico": bool(r.preco_publico),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "table": {
            "name": "knowledge_documents",
            "columns": schema,
        },
        "rows": parsed_rows,
    }
