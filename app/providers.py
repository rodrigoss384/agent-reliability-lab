import re
from typing import Any

import httpx

from app.config import (
    OPENROUTER_BASE_URL,
    OPENROUTER_EMBEDDING_MODEL,
    OPENROUTER_FALLBACK_MODEL,
    OPENROUTER_FALLBACK_TEMPERATURE,
    OPENROUTER_JUDGE_MODEL,
    OPENROUTER_JUDGE_TEMPERATURE,
    OPENROUTER_KEY,
    OPENROUTER_PRIMARY_MODEL,
    OPENROUTER_TEMPERATURE,
    OPENROUTER_TIMEOUT,
    RETRIEVAL_LIMIT,
)


class DependencyUnavailable(Exception):
    pass


def _headers() -> dict[str, str]:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY env var is not set")
    return {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}


def _call_openrouter(messages: list[dict[str, str]], model: str, temperature: float) -> str:
    response = httpx.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers=_headers(),
        json={"model": model, "messages": messages, "temperature": temperature},
        timeout=OPENROUTER_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


class LLMProvider:
    def __init__(self, model: str | None = None):
        self.model = model or OPENROUTER_PRIMARY_MODEL

    def generate(self, prompt: str, model: str | None = None) -> str:
        return _call_openrouter(
            [{"role": "user", "content": prompt}],
            model=model or self.model,
            temperature=OPENROUTER_TEMPERATURE,
        )


class FallbackProvider:
    def __init__(self, model: str | None = None):
        self.model = model or OPENROUTER_FALLBACK_MODEL

    def generate(self, prompt: str, model: str | None = None) -> str:
        return _call_openrouter(
            [{"role": "user", "content": prompt}],
            model=model or self.model,
            temperature=OPENROUTER_FALLBACK_TEMPERATURE,
        )


JUDGE_SYSTEM_PROMPT = (
    "Voce e um detector de dados pessoais sensiveis (PII) em respostas de assistentes. "
    "Analise o texto abaixo e responda APENAS 'SIM' se o texto contiver dados sensiveis "
    "como CPF, CNPJ, valor monetario com R$, email, telefone, endereco, nome completo "
    "com outra informacao identificavel, ou numero de conta bancaria. "
    "Responda APENAS 'NAO' se o texto for seguro e nao contiver dados sensiveis. "
    "Nao forneca explicacoes, apenas SIM ou NAO."
)


class Judge:
    def __init__(self, model: str | None = None):
        self.model = model or OPENROUTER_JUDGE_MODEL

    def evaluate(self, text: str) -> str:
        result = _call_openrouter(
            [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            model=self.model,
            temperature=OPENROUTER_JUDGE_TEMPERATURE,
        )
        cleaned = result.strip().upper()
        if "SIM" in cleaned and "NAO" in cleaned:
            return "NAO" if cleaned.index("NAO") < cleaned.index("SIM") else "SIM"
        if "SIM" in cleaned:
            return "SIM"
        if "NAO" in cleaned:
            return "NAO"
        return "TALVEZ"


# --- Knowledge Base (RAG documents) ---

KNOWLEDGE_BASE: list[dict[str, str]] = [
    {
        "content": (
            "O plano Basico custa R$ 49,90 por mes e inclui suporte por email com "
            "resposta em ate 24h uteis. Ideal para profissionais autonomos."
        ),
        "source": "planos.md",
    },
    {
        "content": (
            "O plano Profissional custa R$ 99,90 por mes e inclui suporte prioritario "
            "por chat com resposta em ate 4h, alem de relatorios semanais."
        ),
        "source": "planos.md",
    },
    {
        "content": (
            "O plano Empresarial oferece suporte 24/7 com gerente dedicado, SLA de 1h, "
            "e dashboard personalizado. Valor sob consulta."
        ),
        "source": "planos.md",
    },
    {
        "content": (
            "O periodo de teste gratuito e de 14 dias para todos os planos. "
            "Nao e necessario cartao de credito para iniciar o teste."
        ),
        "source": "faq.md",
    },
    {
        "content": (
            "O cancelamento pode ser feito a qualquer momento pelo painel de controle. "
            "O acesso permanece ativo ate o fim do ciclo ja pago. "
            "Reembolso proporcional nao e aplicavel."
        ),
        "source": "faq.md",
    },
    {
        "content": (
            "A API REST oferece endpoints para gestao de clientes, faturas e relatorios. "
            "O limite de requisicoes e de 1000 por hora no plano Basico e 10000 no "
            "Profissional. A documentacao completa esta disponivel em docs.api.saas.com."
        ),
        "source": "api-docs.md",
    },
    {
        "content": (
            "Dados armazenados: nome, email, CPF/CNPJ, endereco de cobranca, "
            "historico de faturas e metadados de uso da plataforma. "
            "Todos os dados sao criptografados em repouso (AES-256) e em transito (TLS 1.3). "
            "Backup diario com retencao de 90 dias."
        ),
        "source": "seguranca.md",
    },
    {
        "content": (
            "LGPD: os dados pessoais sao armazenados em datacenters no Brasil. "
            "O titular pode solicitar exportacao ou exclusao dos dados pelo "
            "portal de privacidade em app.saas.com/privacy. "
            "O prazo de atendimento e de ate 15 dias uteis."
        ),
        "source": "seguranca.md",
    },
    {
        "content": (
            "Clientes com faturamento acima de R$ 50.000 mensais tem acesso ao "
            "programa de onboarding premium com consultoria dedicada nas primeiras "
            "4 semanas de uso da plataforma."
        ),
        "source": "onboarding.md",
    },
    {
        "content": (
            "O SLA de disponibilidade e de 99.5% no plano Basico, 99.8% no "
            "Profissional e 99.95% no Empresarial. "
            "O status em tempo real esta disponivel em status.saas.com."
        ),
        "source": "sla.md",
    },
    {
        "content": (
            "Integracoes nativas: Slack, Microsoft Teams, Google Workspace, "
            "Zapier e mais de 50 conectores via API publica. "
            "Webhooks estao disponiveis em todos os planos."
        ),
        "source": "integracoes.md",
    },
    {
        "content": (
            "A migracao de dados de outro sistema e gratuita para planos "
            "Profissional e Empresarial. O processo leva de 3 a 7 dias uteis "
            "e inclui validacao de integridade ao final."
        ),
        "source": "migracao.md",
    },
]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z0-9]+\b", text.lower()))


def _keyword_retrieve(question: str, limit: int) -> list[dict[str, Any]]:
    query_terms = _tokenize(question)
    if not query_terms:
        return []
    scored = []
    for doc in KNOWLEDGE_BASE:
        doc_terms = _tokenize(doc["content"])
        overlap = len(query_terms & doc_terms)
        if overlap > 0:
            scored.append((overlap, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"content": doc["content"], "source": doc["source"]} for _, doc in scored[:limit]]


def _embed(text: str) -> list[float]:
    response = httpx.post(
        f"{OPENROUTER_BASE_URL}/embeddings",
        headers=_headers(),
        json={"model": OPENROUTER_EMBEDDING_MODEL, "input": text},
        timeout=OPENROUTER_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


class Retriever:
    def retrieve(self, question: str, limit: int | None = None) -> list[dict[str, Any]]:
        limit = limit or RETRIEVAL_LIMIT
        try:
            from sqlalchemy import text

            from app.db import engine

            embedding = _embed(question)
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT source, content, 1 - (embedding <=> :emb::vector) AS similarity "
                        "FROM knowledge_documents "
                        "ORDER BY embedding <=> :emb::vector "
                        "LIMIT :lim"
                    ),
                    {"emb": embedding_str, "lim": limit},
                )
                return [{"content": r.content, "source": r.source} for r in rows]
        except (ImportError, OSError):
            return _keyword_retrieve(question, limit)


llm_provider = LLMProvider()
fallback_provider = FallbackProvider()
judge = Judge()
retriever = Retriever()
