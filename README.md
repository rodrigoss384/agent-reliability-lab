<p align="center">
  <img src="docs/logo.svg" alt="Agent Reliability Lab" width="640">
</p>

<p align="center">
  <a href="https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0"><img src="https://img.shields.io/badge/commit-v1.0.0-blue?logo=git&logoColor=white" alt="Commit"></a>
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/fastapi-0.141-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/react-19-61DAFB?logo=react&logoColor=black" alt="React 19">
  <img src="https://img.shields.io/badge/typescript-5-3178C6?logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/postgresql-pgvector-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL pgvector">
  <img src="https://img.shields.io/badge/redis-7-DC382D?logo=redis&logoColor=white" alt="Redis 7">
  <img src="https://img.shields.io/badge/tailwind-4-06B6D4?logo=tailwindcss&logoColor=white" alt="Tailwind CSS 4">
  <img src="https://img.shields.io/badge/vite-8-646CFF?logo=vite&logoColor=white" alt="Vite">
  <img src="https://img.shields.io/badge/vitest-4-6E9F18?logo=vitest&logoColor=white" alt="Vitest">
  <img src="https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
</p>

---

Laboratório de confiabilidade para agentes de IA. Demonstração reproduzível de um pipeline RAG com guardrails que previnem vazamento de dados sensíveis (PII) — antes e depois da chamada ao LLM, mais avaliação por juiz LLM.

## Arquitetura

```mermaid
flowchart LR
    U[Usuário] -->|pergunta| FE[Frontend<br/>React 19 + Tailwind 4]
    FE -->|POST /api/chat| API[FastAPI<br/>Pipeline RAG]
    API -->|1. embedding search| PG[(PostgreSQL<br/>pgvector)]
    API -->|2. pre-guardrail regex| API
    API -->|3. generate| OR[OpenRouter<br/>Gemini Flash]
    OR -->|4. candidate| API
    API -->|5. post-guardrail regex| API
    API -->|6. evaluate| NJ[NVIDIA NIM<br/>Llama Judge]
    NJ -->|SIM/NAO| API
    API -->|sessions| RD[(Redis)]
    API -->|response| FE
    PG -->|embeddings| NE[NVIDIA NIM<br/>Nemotron Embed 1B]
    NE -->|seed| PG
```

1. **Retrieval** — busca semântica no PostgreSQL/pgvector via NVIDIA NIM embeddings (`nvidia/nemotron-3-embed-1b`, 2048 dim)
2. **Pré-guardrail** — regex bloqueia chunks com `R$`, CPF, CNPJ, e-mail antes do LLM (chunks com flag `preco_publico` ignoram `R$`)
3. **Geração** — chain OpenRouter primário → NVIDIA NIM fallback automático quando primário atinge rate limit
4. **Pós-guardrail** — regex na resposta candidata + judge LLM no NVIDIA NIM avalia se contém PII
5. **Sessões** — Redis com TTL configurável (fallback memória), lock por `session_id`

## O que está implementado

- Pipeline RAG completo: retrieval → pré-guardrail (regex) → geração (chain OpenRouter primário, NVIDIA NIM fallback) → pós-guardrail (regex + judge LLM no NVIDIA NIM)
- Detecção de PII sintética: CPF, CNPJ, e-mail, valores monetários (`R$`)
- Bloqueio duro no input do usuário: regex no `request.question` antes do IntentClassifier/retrieval/LLM (estado `bloqueado-na-entrada`)
- Pré-guardrail com flag `preco_publico`: chunks de catálogo público (preços de planos) passam sem bloquear `R$`
- Pós-guardrail com bypass de catálogo: se a resposta ecoa `R$` mas veio de chunk `preco_publico`, judge é pulado e resposta é entregue
- Sentinela `judge_block` em `pii_categories` quando judge detecta PII sem categoria específica de regex
- Timings separados: `pre_guardrail_ms`, `llm_ms`, `pii_regex_ms`, `pii_judge_ms` (soma em `post_guardrail_ms`)
- Chain de chat = exatamente 2 provedores: OpenRouter primário + NVIDIA NIM fallback automático (visível em `trace.fallback_used`)
- Embedding primário = NVIDIA NIM (`nvidia/nemotron-3-embed-1b`, 2048 dim); judge também no NVIDIA NIM
- Busca semântica no PostgreSQL/pgvector (2048 dim) — falha de embedding propaga `DependencyUnavailable` (sem fallback)
- Estado `limite-cota`: quando todos os provedores esgotam quota gratuita, UI mostra instrução clara
- Sessões com lock por `session_id` (409 em concorrência), histórico sanitizado, TTL configurável
- Persistência Redis com fallback automático para memória
- Health check real de PostgreSQL, Redis e embedding provider
- Bootstrap automático ao subir: `alembic upgrade head` + seed com retry e idempotência
- Table Editor READ-ONLY (`GET /api/admin/knowledge-documents`): inspeção de `knowledge_documents` com schema de colunas, resumo estatístico do embedding (norma, min/max/mean, first5/last5) e flag `preco_publico`
- Interface React 19 + Tailwind CSS 4 com tema Dracula, trace de evidência sanitizada, métricas de chunks, botões "Nova conversa" e "Ver Tabelas de Dados"
- 63 testes de integração (pytest), 24 testes unitários (vitest), E2E (Playwright, opcional)
- Toda configuração via `.env`

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic |
| Banco | PostgreSQL 17 + pgvector (busca semântica), Redis 7 (sessões) |
| LLM / Embeddings | OpenRouter API (primário do chat); NVIDIA NIM (fallback chat, embedding primário, judge) — endpoint OpenAI-compatible em `integrate.api.nvidia.com/v1` |
| Frontend | React 19, TypeScript 5, Vite 8, Tailwind CSS 4 |
| Testes | pytest, vitest, Playwright, ruff |
| Infra | Docker Compose (4 serviços: postgres, redis, api, frontend) |

---

## O que é possível testar

Cada item é validável via frontend (http://localhost:5173) ou curl direto na API (http://localhost:8000). Os exemplos são ilustrativos do comportamento esperado — o foco é o conceito e a tecnologia demonstrada. Cada item está vinculado ao commit da entrega inicial.

- [ ] **Detecção de PII por regex no input do usuário** — bloqueio duro antes do pipeline.
  *Conceito: defesa em profundidade.* *Tecnologias: regex (`is_sensitive`, `classify_pii`), Pydantic, FastAPI middleware.*
  Exemplo: `"Meu CPF é 123.456.789-00"` → estado `bloqueado-na-entrada` antes do LLM ser chamado.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Detecção de PII por regex em chunks do retrieval** — pré-guardrail exclui contexto sensível antes do LLM.
  *Conceito: segurança de contexto RAG.* *Tecnologias: pgvector similarity search, regex em loop sobre chunks retornados.*
  Exemplo: chunk com `R$ 50.000` (threshold de faturamento) é bloqueado, LLM recebe apenas contexto limpo.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Detecção de PII por juiz LLM** — judge NVIDIA NIM avalia resposta candidata após geração.
  *Conceito: AI safety em duas camadas (regex + LLM-as-judge).* *Tecnologias: NVIDIA NIM (Llama 3.1 8B), sentinela `judge_block` em `pii_categories`.*
  Exemplo: `"Qual o CPF do João?"` → LLM alucina CPF → judge responde SIM → `bloqueado-na-saida`.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Flag `preco_publico` libera chunks de catálogo público** — diferencia valor monetário público de pessoal.
  *Conceito: classificação semântica de dado vs padrão de caractere.* *Tecnologias: coluna Postgres `preco_publico`, branch no regex pré/pós-guardrail, bypass do judge quando resposta ecoa valor de catálogo.*
  Exemplo: `"Quanto custa o plano básico?"` → resposta entregue com `R$ 49,90` (sem bloqueio).
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Retrieval RAG com embeddings NVIDIA NIM** — busca semântica 2048-dim no pgvector.
  *Conceito: vector search.* *Tecnologias: pgvector, NVIDIA NIM Nemotron 3 Embed 1B, cosine distance (`<=>`).*
  Exemplo: pergunta técnica → top-5 chunks ranqueados por similaridade → contexto enviado ao LLM.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Chain de fallback OpenRouter → NVIDIA NIM** — degradação graciosa em rate limit.
  *Conceito: reliability de cadeia LLM em produção.* *Tecnologias: try/except encadeado, `RateLimitError` custom, `trace.fallback_used`.*
  Exemplo: OpenRouter atinge cota → NVIDIA NIM assume → trace mostra `fallback_used=true` e `model_used` apontando para NIM.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Table Editor (READ-ONLY)** — inspeção de dados para auditoria e teste de estratégias RAG.
  *Conceito: observabilidade de dados para o testador.* *Tecnologias: FastAPI admin endpoint, pgvector cast para text, resumo estatístico em Python.*
  Exemplo: botão "Ver Tabelas de Dados" no header → overlay fullscreen com 12 docs, sparklines de embedding e badge `preco_publico`.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Persistência de sessão com TTL** — Redis com fallback automático para memória.
  *Conceito: agentes stateful.* *Tecnologias: redis-py, sliding TTL, in-memory dict como fallback gracioso.*
  Exemplo: conversa de 2 turnos sobrevive após refresh, expira em 24h.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Lock por session_id** — concorrência segura.
  *Conceito: race condition prevention.* *Tecnologias: `threading.Lock` em dict Python, HTTP 409.*
  Exemplo: 2 requests simultâneos na mesma sessão → segundo retorna 409 `session_busy`.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Bloqueio por limite de cota** — degradação final com mensagem instrutiva.
  *Conceito: graceful degradation.* *Tecnologias: estado `limite-cota` no trace, banner no frontend.*
  Exemplo: ambos provedores esgotam → UI mostra instrução para configurar `NVIDIA_NIM_API_KEY`.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Saudação pula retrieval via heurística + IntentClassifier** — economia de embedding em entradas óbvias.
  *Conceito: latência vs precisão.* *Tecnologias: regex de saudação pt-BR, classifier NVIDIA NIM Llama 3.1 8B.*
  Exemplo: `"Oi"` → `intent_skipped_retrieval=true`, `retrieved_count=0`, latência menor.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

- [ ] **Contrato OpenAPI design-first** — fonte única de verdade para integração.
  *Conceito: contract-first development.* *Tecnologias: OpenAPI 3.1.1, exposição automática via `/docs` e `/openapi.json`.*
  Exemplo: qualquer cliente HTTP pode gerar SDK a partir do YAML em `openapi/rag-pii-guardrails.yaml`.
  Commit: [`v1.0.0`](https://github.com/rodrigoss384/agent-reliability-lab/commit/v1.0.0)

---

## Como usar

### Pré-requisitos

- Docker + Docker Compose
- Chave da [OpenRouter](https://openrouter.ai/keys) (gratuita)

### 1. Configurar

```bash
cp .env.example .env
# Edite .env e cole sua OPENROUTER_API_KEY
```

### 2. Subir

```bash
docker compose up -d
```

O container `api` roda automaticamente migration + seed com embeddings (12 documentos fictícios de um SaaS). A inicialização leva ~15s.

### 3. Acessar

- **Frontend:** http://localhost:5173
- **API docs:** http://localhost:8000/docs

---

## Configurando Fallback NVIDIA NIM (recomendado)

O chain de chat usa **OpenRouter como primário** e **NVIDIA NIM como fallback automático** quando o primário atinge rate limit. Embedding e judge também rodam no NVIDIA NIM (sem fallback).

### Criar conta NVIDIA

1. Acesse [https://build.nvidia.com](https://build.nvidia.com)
2. Login com Google ou GitHub (sem cartão de crédito)
3. Vá em [https://build.nvidia.com/settings/keys](https://build.nvidia.com/settings/keys) e gere uma API key (formato `nvapi-...`)
4. Créditos trial inclusos para Developer Program

### Adicionar ao `.env`

```env
NVIDIA_NIM_API_KEY=nvapi-...
```

### Limites gratuitos

| Provedor | Limite |
|----------|--------|
| OpenRouter (free models) | 50 req/dia (sem credits); 1.000 req/dia com ≥10 credits |
| NVIDIA NIM (Developer Program) | Créditos trial para prototipagem; modelo `llama-3.1-8b-instruct` e `nemotron-3-embed-1b` cobertos |

### Como o fallback aparece no trace

Quando o primário OpenRouter atinge rate limit, o chain automaticamente chama o fallback NVIDIA NIM. O trace retornado em `/api/chat` mostra:

```json
{
  "model_used": "meta/llama-3.1-8b-instruct",
  "trace": {
    "primary_model": "poolside/laguna-s-2.1:free",
    "fallback_used": true,
    "judge_model": "meta/llama-3.1-8b-instruct",
    "embedding_provider": "nvidia_nim"
  }
}
```

Sem `NVIDIA_NIM_API_KEY`, o app continua funcionando — rate limit do OpenRouter retorna `limite-cota` com mensagem instrutiva na UI apontando para configuração da chave NIM.

---

## Desenvolvimento local (sem Docker)

```bash
cp .env.example .env

# Suba só infra
docker compose up -d postgres redis

# Migration + seed
uv run python scripts/bootstrap.py

# Backend (Terminal 1)
uv run uvicorn app.main:app --reload

# Frontend (Terminal 2)
npm --prefix frontend run dev
```

### Rodar testes

```bash
uv run pytest tests/ -v                    # 63 testes de integração
npm --prefix frontend run test             # 24 testes unitários (vitest)
npm --prefix frontend run test:browser     # E2E (requer backend)
uv run ruff check app/ tests/              # Lint
```

---

## API

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/api/chat` | Processa pergunta no pipeline RAG com guardrails PII |
| `GET` | `/api/conversation/{session_id}` | Recupera histórico sanitizado (apenas turnos `entregue`) |
| `GET` | `/api/health` | Consulta saúde das dependências (PostgreSQL, Redis, embedding) |
| `GET` | `/api/models` | Lista modelos configurados (primário, fallback) |
| `GET` | `/api/admin/knowledge-documents` | Lista documentos de conhecimento (Table Editor, READ-ONLY, dev-only) |

### POST /api/chat

```json
// Request
{ "question": "Como funciona o cancelamento?", "session_id": "opcional" }

// Response 200
{
  "session_id": "uuid",
  "answer": "O cancelamento pode ser feito a qualquer momento...",
  "model_used": "google/gemini-2.0-flash-001",
  "guardrail_state": "entregue",
  "trace": {
    "retrieved_count": 2,
    "used_count": 1,
    "blocked_count": 1,
    "guardrail_state": "entregue",
    "total_ms": 1234,
    "sources": ["faq.md"],
    "input_pii_detected": false,
    "pii_categories": [],
    "pii_categories_retrieval": ["R$"],
    "judge_decision": "NAO"
  }
}
```

Estados `guardrail_state`: `entregue`, `bloqueado-na-entrada`, `bloqueado-na-saida`, `falha-segura`, `limite-cota`.

### GET /api/admin/knowledge-documents

```bash
# Listar todos (paginado)
curl 'http://localhost:8000/api/admin/knowledge-documents?limit=20'

# Filtrar por source
curl 'http://localhost:8000/api/admin/knowledge-documents?source=planos.md'
```

---

## Estrutura do projeto

```text
.
├── app/
│   ├── main.py              # FastAPI — endpoints e pipeline RAG
│   ├── providers.py          # LLMProvider (OpenRouter), NvidiaNimProvider (fallback chat), NvidiaNimEmbeddingProvider, NvidiaNimJudge, Retriever
│   ├── models.py             # SQLAlchemy — KnowledgeDocument (pgvector)
│   ├── db.py                 # Engine e sessão do banco
│   ├── config.py             # Configuração centralizada (.env)
│   └── seed.py               # Popula banco com embeddings via NVIDIA NIM
├── frontend/
│   └── src/
│       ├── api/client.ts     # Cliente HTTP para /api/chat e /api/conversation
│       └── features/rag-pii-chat/
│           ├── ChatScreen.tsx       # Componente principal
│           ├── TableEditor.tsx      # Overlay READ-ONLY para inspeção de dados
│           ├── ChatScreen.test.tsx  # 24 testes vitest
│           └── ChatScreen.spec.ts   # 9 testes Playwright
├── tests/
│   └── integration/
│       └── test_chat_guardrail_slice.py  # 63 testes pytest
├── openapi/
│   └── rag-pii-guardrails.yaml    # Contrato OpenAPI 3.1 design-first
├── migrations/                    # Alembic — 1 migration consolidada
├── scripts/
│   └── bootstrap.py               # Migration + seed + metadata flags com retry
├── compose.yaml                   # 4 serviços Docker
├── Dockerfile                     # Build do backend
├── frontend/Dockerfile            # Build do frontend
├── .env.example                   # Template de variáveis de ambiente
└── docs/
    └── logo.svg
```
