import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.providers as providers_module
from app.main import app
from app.providers import (
    DependencyUnavailable,
    RateLimitError,
    _is_obvious_non_question,
    intent_classifier,
    judge,
    llm_provider,
    nvidia_nim_fallback_provider,
    retriever,
)


@pytest.fixture(autouse=True)
def _clean_sessions():
    main_module._memory_store.clear()
    try:
        r = main_module._get_redis()
        if r:
            for key in r.keys("rag:session:*"):
                r.delete(key)
    except Exception:  # noqa: BLE001, S110
        pass
    yield


def test_sensitive_retrieved_chunk_is_excluded_before_provider(monkeypatch):
    permitted_chunk = {
        "content": "O plano oferece suporte por email e chat com cobertura nacional.",
        "source": "planos.md"
    }
    sensitive_chunk = {
        "content": "Cliente Acme Corp CNPJ: 12.345.678/0001-99, email: contact@acme.com, renewal 2026-12-31, value R$ 15000.",
        "source": "acme_contract.txt"
    }

    mock_retrieve = MagicMock(return_value=[permitted_chunk, sensitive_chunk])
    monkeypatch.setattr(retriever, "retrieve", mock_retrieve)

    spy_generate = MagicMock(return_value=("Mocked LLM generation response.", None))
    monkeypatch.setattr(llm_provider, "generate", spy_generate)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa o plano Basico?", "session_id": "session-test"}
    )

    assert response.status_code == 200
    data = response.json()

    trace = data["trace"]
    assert trace["retrieved_count"] == 2
    assert trace["blocked_count"] > 0, "No chunks were blocked by the guardrail"
    assert trace["used_count"] < trace["retrieved_count"], "Used count should be less than retrieved count"

    assert spy_generate.called, "LLM provider was not called"
    called_messages = spy_generate.call_args.kwargs["messages"]

    called_text = str(called_messages)
    assert "12.345.678/0001-99" not in called_text, "CNPJ reached the provider"
    assert "contact@acme.com" not in called_text, "Email reached the provider"
    assert "R$ 15000" not in called_text, "Value reached the provider"
    assert "acme_contract.txt" not in trace["sources"], "Blocked source was exposed in trace"


def test_post_guardrail_regex_blocks_response_with_sensitive_data(monkeypatch):
    permitted_chunk = {
        "content": "O plano basico inclui suporte por email com resposta em ate 24h.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    spy_primary = MagicMock(return_value=("O plano custa R$ 5.000 por mes para empresas.", None))
    monkeypatch.setattr(llm_provider, "generate", spy_primary)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa o plano empresarial?", "session_id": "session-post"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "bloqueado-na-saida"
    assert "R$" not in data["answer"]
    assert "5.000" not in data["answer"]


def test_judge_nao_preserves_clean_response(monkeypatch):
    permitted_chunk = {
        "content": "Suporte tecnico disponivel 24h por chat e telefone.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Voce pode entrar em contato pelo chat ou telefone.", None)))

    spy_judge = MagicMock(return_value="NAO")
    monkeypatch.setattr(judge, "evaluate", spy_judge)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Como funciona o suporte?", "session_id": "session-judge"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "entregue"
    assert data["answer"] == "Voce pode entrar em contato pelo chat ou telefone."

    spy_judge.assert_called_once_with("Voce pode entrar em contato pelo chat ou telefone.")


def test_judge_sim_blocks_sensitive_response(monkeypatch):
    permitted_chunk = {
        "content": "O plano oferece cobertura nacional e suporte dedicado.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("A adesao custa 299 reais, sem taxas adicionais.", None)))

    spy_judge = MagicMock(return_value="SIM")
    monkeypatch.setattr(judge, "evaluate", spy_judge)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa a adesao?", "session_id": "session-judge-sim"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "bloqueado-na-saida"
    assert "299" not in data["answer"]


def test_judge_inconclusive_returns_safe_failure(monkeypatch):
    permitted_chunk = {
        "content": "Dados do cliente serao exibidos no painel.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Os dados aparecem no canto superior direito.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="TALVEZ"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Onde vejo meus dados?", "session_id": "session-fail"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "falha-segura"
    assert "dados" not in data["answer"].lower() or "Os dados" not in data["answer"]


def test_judge_error_returns_safe_failure(monkeypatch):
    permitted_chunk = {
        "content": "Relatorio semanal disponivel toda sexta-feira.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Relatorio liberado as 18h.", None)))

    def failing_judge(_text):
        raise RuntimeError("judge service timeout")
    monkeypatch.setattr(judge, "evaluate", failing_judge)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quando sai o relatorio?", "session_id": "session-judge-err"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "entregue"
    assert data["answer"] == "Relatorio liberado as 18h."


def test_regex_guardrail_error_returns_safe_failure(monkeypatch):
    permitted_chunk = {
        "content": "Documento generico.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Resposta segura.", None)))

    def failing_is_sensitive(_content):
        raise ConnectionError("regex engine crashed")
    monkeypatch.setattr(main_module, "is_sensitive", failing_is_sensitive)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Pergunta generica?", "session_id": "session-regex-err"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "falha-segura"


def test_primary_failure_uses_fallback_once(monkeypatch):
    permitted_chunk = {
        "content": "O plano oferece suporte por email com resposta em ate 24h.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    spy_primary = MagicMock(side_effect=RuntimeError("primary timeout"))
    monkeypatch.setattr(llm_provider, "generate", spy_primary)

    spy_fallback = MagicMock(return_value=("Resposta via fallback com sucesso.", None))
    monkeypatch.setattr(nvidia_nim_fallback_provider, "generate", spy_fallback)

    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o plano Basico?", "session_id": "session-fallback"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "entregue"
    assert data["answer"] == "Resposta via fallback com sucesso."
    assert data["model_used"] == nvidia_nim_fallback_provider.model
    assert data["trace"]["fallback_used"] is True
    assert data["trace"]["primary_model"] == llm_provider.model

    spy_primary.assert_called_once()
    spy_fallback.assert_called_once()


def test_both_providers_fail_returns_safe_failure_no_duplicate_retry(monkeypatch):
    permitted_chunk = {
        "content": "Contrato renovado anualmente.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    spy_primary = MagicMock(side_effect=RuntimeError("primary crash"))
    monkeypatch.setattr(llm_provider, "generate", spy_primary)

    spy_fallback = MagicMock(side_effect=RuntimeError("fallback crash"))
    monkeypatch.setattr(nvidia_nim_fallback_provider, "generate", spy_fallback)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Sobre contratos?", "session_id": "session-no-retry"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "falha-segura"

    assert spy_primary.call_count == 1
    assert spy_fallback.call_count == 1


def test_retriever_unavailable_returns_503(monkeypatch):
    def failing_retrieve(_question, limit=5):
        raise DependencyUnavailable("pgvector connection refused")
    monkeypatch.setattr(retriever, "retrieve", failing_retrieve)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o SLA do plano Basico disponivel?", "session_id": "session-dep"}
    )

    assert response.status_code == 503
    data = response.json()
    assert data["guardrail_state"] == "falha-segura"


def test_post_chat_without_question_returns_422():
    client = TestClient(app)
    response = client.post("/api/chat", json={"session_id": "s1"})
    assert response.status_code == 422


def test_post_chat_with_empty_question_returns_422():
    client = TestClient(app)
    response = client.post("/api/chat", json={"question": "", "session_id": "s1"})
    assert response.status_code == 422


def test_post_chat_with_invalid_json_returns_422():
    client = TestClient(app)
    response = client.post("/api/chat", content="not json", headers={"Content-Type": "application/json"})
    assert response.status_code >= 400


def test_invalid_request_does_not_trigger_pipeline(monkeypatch):
    spy_retrieve = MagicMock()
    monkeypatch.setattr(retriever, "retrieve", spy_retrieve)

    client = TestClient(app)
    response = client.post("/api/chat", json={"session_id": "s1"})

    assert response.status_code == 422
    spy_retrieve.assert_not_called()


def test_health_does_not_leak_secrets():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    sentinels = ["token", "key", "secret", "password", "api_key", "url", "@", "prompt"]
    body_str = str(data).lower()
    for sentinel in sentinels:
        assert sentinel not in body_str, f"sentinela '{sentinel}' encontrada em /api/health"


def test_models_does_not_leak_secrets():
    client = TestClient(app)
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    sentinels = ["token", "key", "secret", "password", "api_key", "url", "prompt"]
    body_str = str(data).lower()
    for sentinel in sentinels:
        assert sentinel not in body_str, f"sentinela '{sentinel}' encontrada em /api/models"


def test_new_session_returns_unique_id(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("ID gerado.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post("/api/chat", json={"question": "Pergunta de teste"})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["session_id"] != "session-default"
    assert len(data["session_id"]) > 0


def test_get_conversation_returns_404_for_unknown_session():
    client = TestClient(app)
    response = client.get("/api/conversation/nao-existe-12345")
    assert response.status_code == 404


def test_session_history_contains_only_delivered_turns(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Resposta segura.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    r1 = client.post("/api/chat", json={"question": "Q1?", "session_id": "hist-s1"})
    assert r1.status_code == 200
    assert r1.json()["guardrail_state"] == "entregue"

    monkeypatch.setattr(main_module, "is_sensitive", MagicMock(return_value=True))
    r2 = client.post("/api/chat", json={"question": "Q2?", "session_id": "hist-s1"})
    assert r2.status_code == 200

    response = client.get("/api/conversation/hist-s1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["turns"]) == 1
    assert data["turns"][0]["guardrail_state"] == "entregue"
    assert "created_at" in data
    assert "session_id" in data


def test_session_history_does_not_contain_raw_data(monkeypatch):
    sensitive_chunk = {
        "content": "Cliente com CPF: 123.456.789-00.",
        "source": "dados.txt"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[sensitive_chunk]))

    client = TestClient(app)
    r = client.post("/api/chat", json={"question": "Dados?", "session_id": "hist-s2"})
    assert r.status_code == 200

    response = client.get("/api/conversation/hist-s2")
    assert response.status_code == 200
    data = response.json()
    body_str = str(data)
    assert "CPF" not in body_str
    assert "123.456.789-00" not in body_str


def test_session_expired_returns_404(monkeypatch):
    base_time = 1000000.0
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Resposta.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))
    monkeypatch.setattr(main_module.time, "time", MagicMock(return_value=base_time))

    client = TestClient(app)
    r = client.post("/api/chat", json={"question": "Q?", "session_id": "ttl-s1"})
    assert r.status_code == 200

    monkeypatch.setattr(main_module.time, "time", MagicMock(return_value=base_time + 86401))

    response = client.get("/api/conversation/ttl-s1")
    assert response.status_code == 404


def test_session_activity_renews_ttl(monkeypatch):
    base_time = 1000000.0
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("X.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    time_mock = MagicMock(return_value=base_time)
    monkeypatch.setattr(main_module.time, "time", time_mock)

    client = TestClient(app)
    r1 = client.post("/api/chat", json={"question": "Q1?", "session_id": "ttl-s2"})
    assert r1.status_code == 200

    time_mock.return_value = base_time + 43200
    r2 = client.post("/api/chat", json={"question": "Q2?", "session_id": "ttl-s2"})
    assert r2.status_code == 200

    time_mock.return_value = base_time + 43200 + 86401
    response = client.get("/api/conversation/ttl-s2")
    assert response.status_code == 404


def test_health_returns_unhealthy_when_retriever_fails(monkeypatch):
    def failing_retrieve(_question, limit=5):
        raise DependencyUnavailable("pgvector connection refused")
    monkeypatch.setattr(retriever, "retrieve", failing_retrieve)

    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unhealthy"


def test_concurrent_chat_same_session_returns_409(monkeypatch):
    barrier = threading.Event()
    resolver = threading.Event()

    def slow_retrieve(_question, limit=5):
        resolver.set()
        barrier.wait(timeout=5)
        return []

    monkeypatch.setattr(retriever, "retrieve", slow_retrieve)
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("OK.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)

    results = {}

    def first_request():
        resp = client.post("/api/chat", json={"question": "Qual e o SLA do plano?", "session_id": "lock-s1"})
        results["first"] = (resp.status_code, resp.json())

    t = threading.Thread(target=first_request)
    t.start()
    resolver.wait(timeout=5)
    import time as _t
    _t.sleep(0.1)

    response2 = client.post("/api/chat", json={"question": "Quanto custa a mensalidade?", "session_id": "lock-s1"})
    results["second"] = (response2.status_code, response2.json())

    barrier.set()
    t.join(timeout=5)

    assert results["second"][0] == 409, f"esperado 409, recebido {results['second'][0]}"
    assert results["first"][0] == 200

    conv = client.get("/api/conversation/lock-s1")
    assert conv.status_code in (200, 404)
    if conv.status_code == 200:
        assert len(conv.json()["turns"]) == 1


def test_different_sessions_are_independent(monkeypatch):
    barrier = threading.Event()
    resolver = threading.Event()

    def slow_retrieve(_question, limit=5):
        if _question == "Q1?":
            resolver.set()
        barrier.wait(timeout=5)
        return []

    monkeypatch.setattr(retriever, "retrieve", slow_retrieve)
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("OK.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)

    results = {}

    def first_request():
        resp = client.post("/api/chat", json={"question": "Q1?", "session_id": "ind-s1"})
        results["first"] = (resp.status_code, resp.json())

    t = threading.Thread(target=first_request)
    t.start()
    resolver.wait(timeout=5)
    import time as _t
    _t.sleep(0.1)

    response2 = client.post("/api/chat", json={"question": "Q2?", "session_id": "ind-s2"})
    results["second"] = (response2.status_code, response2.json())

    barrier.set()
    t.join(timeout=5)

    assert results["first"][0] == 200
    assert results["second"][0] == 200, f"esperado 200, recebido {results['second'][0]}: {results['second'][1]}"


def test_agent_responds_without_rag_on_casual_greeting(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Ola! Sou o Aria. Em que posso ajudar?", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Oi", "session_id": "session-greeting"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "entregue"
    assert data["answer"] == "Ola! Sou o Aria. Em que posso ajudar?"
    assert data["trace"]["rag_used"] is False
    assert data["trace"]["retrieved_count"] == 0
    assert data["trace"]["used_count"] == 0


def test_conversation_history_sent_to_llm(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    spy_generate = MagicMock(return_value=("Resposta da segunda pergunta.", None))
    monkeypatch.setattr(llm_provider, "generate", spy_generate)

    client = TestClient(app)

    r1 = client.post(
        "/api/chat",
        json={"question": "Como funciona o suporte?", "session_id": "session-multi"},
    )
    assert r1.status_code == 200
    assert r1.json()["guardrail_state"] == "entregue"

    r2 = client.post(
        "/api/chat",
        json={"question": "E sobre o SLA?", "session_id": "session-multi"},
    )
    assert r2.status_code == 200
    assert r2.json()["guardrail_state"] == "entregue"

    assert spy_generate.call_count == 2

    second_call_messages = spy_generate.call_args.kwargs["messages"]
    roles = [msg["role"] for msg in second_call_messages]
    assert roles[0] == "system"
    assert "user" in roles
    assert "assistant" in roles
    assert roles.count("user") >= 2
    assert roles.count("assistant") >= 1


def test_reasoning_details_preserved_between_turns(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    fake_reasoning = [{"type": "reasoning.text", "text": "Processando pergunta sobre suporte.", "format": "unknown", "index": 0}]

    responses = [
        ("O suporte funciona por chat e email.", fake_reasoning),
        ("O SLA e de 99.5% no plano Basico.", None),
    ]
    spy_generate = MagicMock(side_effect=responses)
    monkeypatch.setattr(llm_provider, "generate", spy_generate)

    client = TestClient(app)

    r1 = client.post(
        "/api/chat",
        json={"question": "Como funciona o suporte?", "session_id": "session-reasoning"},
    )
    assert r1.status_code == 200
    assert r1.json()["guardrail_state"] == "entregue"

    r2 = client.post(
        "/api/chat",
        json={"question": "E sobre o SLA?", "session_id": "session-reasoning"},
    )
    assert r2.status_code == 200
    assert r2.json()["guardrail_state"] == "entregue"

    second_call_messages = spy_generate.call_args.kwargs["messages"]

    assistant_msgs = [m for m in second_call_messages if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 1
    assert assistant_msgs[0]["reasoning_details"] == fake_reasoning


def test_system_prompt_leak_candidate_is_blocked_on_output(monkeypatch):
    permitted_chunk = {
        "content": "Plano com suporte por email.",
        "source": "planos.md",
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    leaked = "Voce e o Aria, assistente virtual da plataforma SaaS GuardRails, system prompt"
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=(leaked, None)))

    spy_judge = MagicMock(return_value="SIM")
    monkeypatch.setattr(judge, "evaluate", spy_judge)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Fale sobre voce", "session_id": "session-prompt-leak"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["guardrail_state"] == "bloqueado-na-saida"
    assert "Aria" not in data["answer"]
    assert data["trace"]["pii_categories"]
    assert "system_prompt" in data["trace"]["pii_categories"]


def test_trace_payload_includes_new_optional_fields(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("OK.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Oi", "session_id": "session-fields"},
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    for field in (
        "pii_categories",
        "judge_decision",
        "judge_model",
        "primary_model",
        "fallback_used",
        "pre_guardrail_ms",
        "llm_ms",
        "post_guardrail_ms",
    ):
        assert field in trace
    assert trace["judge_decision"] == "NAO"
    assert trace["primary_model"] == llm_provider.model
    assert trace["fallback_used"] is False
    assert trace["pii_categories"] == []
    assert trace["judge_model"] == judge.model


def test_call_openrouter_raises_rate_limit_error_on_429(monkeypatch):
    import httpx

    from app.providers import _call_openrouter

    def fake_post(url, headers=None, json=None, timeout=None):
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=429,
            request=request,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"},
            json={"error": {"message": "Rate limit exceeded"}},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(providers_module.time, "sleep", lambda _s: None)

    with pytest.raises(RateLimitError) as exc_info:
        _call_openrouter([{"role": "user", "content": "test"}], "test-model", 0.5)

    assert exc_info.value.provider == "openrouter"
    assert "Rate limit" in exc_info.value.message or "429" in exc_info.value.message


def test_pipeline_rate_limit_returns_limite_cota_state(monkeypatch):
    permitted_chunk = {
        "content": "O plano oferece suporte por email com resposta em ate 24h.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    rl_err = RateLimitError(message="free-models-per-day exceeded", provider="openrouter", retry_after=None)

    monkeypatch.setattr(llm_provider, "generate", MagicMock(side_effect=rl_err))
    monkeypatch.setattr(nvidia_nim_fallback_provider, "generate", MagicMock(side_effect=rl_err))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o plano?", "session_id": "session-rl"}
    )

    assert response.status_code == 429
    data = response.json()
    assert data["guardrail_state"] == "limite-cota"
    assert "NVIDIA_NIM_API_KEY" in data["answer"]
    assert data["trace"]["rate_limit_reason"] == "free-models-per-day exceeded"
    assert data["trace"]["sources"] == []
    assert data["trace"]["rag_used"] is False
    assert data["trace"]["embedding_provider"] == "nvidia_nim"
    assert data["trace"]["pii_judge_ms"] == 0
    assert data["trace"]["input_pii_detected"] is False


def test_chat_chain_has_exactly_two_providers(monkeypatch):
    """Defesa contra regressao: chain deve ter exatamente OpenRouter + NVIDIA NIM."""
    from app.main import _generate_with_fallbacks

    primary = llm_provider.model
    fallback = nvidia_nim_fallback_provider.model
    assert primary and fallback, "providers nao inicializados"

    spy_primary = MagicMock(return_value=("from primary", None))
    spy_fallback = MagicMock(return_value=("from fallback", None))
    monkeypatch.setattr(llm_provider, "generate", spy_primary)
    monkeypatch.setattr(nvidia_nim_fallback_provider, "generate", spy_fallback)

    _generate_with_fallbacks(
        [{"role": "user", "content": "oi"}],
        primary,
        fallback,
        False,
    )

    assert spy_primary.call_count == 1
    assert spy_fallback.call_count == 0


def test_chat_chain_falls_back_to_nvidia_nim_on_rate_limit(monkeypatch):
    """Rate limit do primario OpenRouter aciona fallback NVIDIA NIM automaticamente."""
    from app.main import _generate_with_fallbacks

    primary = llm_provider.model
    fallback = nvidia_nim_fallback_provider.model

    rl_err = RateLimitError(message="free-models-per-day exceeded", provider="openrouter", retry_after=None)
    monkeypatch.setattr(llm_provider, "generate", MagicMock(side_effect=rl_err))
    monkeypatch.setattr(nvidia_nim_fallback_provider, "generate", MagicMock(return_value=("resposta fallback", None)))

    candidate, _, model_used, fallback_used = _generate_with_fallbacks(
        [{"role": "user", "content": "oi"}],
        primary,
        fallback,
        False,
    )

    assert candidate == "resposta fallback"
    assert model_used == fallback
    assert fallback_used is True


def test_embedding_uses_nvidia_nim_primary(monkeypatch):
    """Retriever usa exclusivamente embedding NVIDIA NIM (sem fallback OpenRouter)."""
    permitted_chunk = {
        "content": "O plano Basico custa R$ 49,90 por mes.",
        "source": "planos.md"
    }

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    from app import db as db_module

    captured: dict[str, Any] = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        embedding = [0.0] * db_module.__dict__.get("NVIDIA_NIM_EMBEDDING_DIM", 2048)
        return FakeResponse({"data": [{"embedding": embedding}]})

    import httpx as httpx_mod
    monkeypatch.setattr(httpx_mod, "post", fake_post)

    class FakeRow:
        def __init__(self, content, source, preco_publico=False):
            self.content = content
            self.source = source
            self.preco_publico = preco_publico

    class FakeRows:
        def __init__(self, rows):
            self._rows = rows

        def __iter__(self):
            return iter(self._rows)

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, _stmt, _params):
            return FakeRows([FakeRow(permitted_chunk["content"], permitted_chunk["source"])])

    class FakeEngine:
        def connect(self):
            return FakeConn()

    monkeypatch.setattr(db_module, "engine", FakeEngine())

    chunks = retriever.retrieve("plano basico", limit=3)

    assert captured["url"].endswith("/embeddings")
    assert "integrate.api.nvidia.com" in captured["url"]
    assert "Bearer" in captured["headers"]["Authorization"]
    assert captured["json"]["model"] == "nvidia/nemotron-3-embed-1b"
    assert captured["json"]["input_type"] == "query"
    assert len(captured["json"]["input"]) == 1
    assert chunks == [{**permitted_chunk, "preco_publico": False}]


def test_embedding_no_fallback_on_error(monkeypatch):
    """Falha no embedding NIM propaga como DependencyUnavailable (sem fallback OpenRouter)."""
    from app.providers import DependencyUnavailable as DU

    def fake_post(*_args, **_kwargs):
        raise RuntimeError("nim down")

    monkeypatch.setattr("httpx.post", fake_post)

    with pytest.raises(DU):
        retriever.retrieve("anything", limit=1)


def test_judge_uses_nvidia_nim(monkeypatch):
    """Judge usa exclusivamente NVIDIA NIM."""
    spy = MagicMock(return_value=("NAO", None))
    monkeypatch.setattr("app.providers._call_nvidia_nim", spy)
    monkeypatch.setattr("app.main.judge", judge)

    decision = judge.evaluate("texto seguro")

    assert decision == "NAO"
    spy.assert_called_once()
    args, _kwargs = spy.call_args
    assert "judge" in args[0][0]["content"].lower() or "PI" in args[0][0]["content"]


def test_obvious_greeting_skips_retrieval_via_heuristic(monkeypatch):
    """Heuristica deve pular retrieval para saudacao curta sem chamar classificador."""
    spy_retrieve = MagicMock(return_value=[])
    monkeypatch.setattr(retriever, "retrieve", spy_retrieve)
    spy_classifier = MagicMock(return_value=True)
    monkeypatch.setattr(intent_classifier, "classify", spy_classifier)

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Ola! Como posso ajudar?", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Oi", "session_id": "session-greeting-1"}
    )

    assert response.status_code == 200
    data = response.json()
    trace = data["trace"]
    assert trace["retrieved_count"] == 0
    assert trace["used_count"] == 0
    assert trace["blocked_count"] == 0
    assert trace["rag_used"] is False
    assert trace["intent_skipped_retrieval"] is True
    spy_retrieve.assert_not_called()
    spy_classifier.assert_not_called()
    assert trace["pii_categories"] == []
    assert trace["pii_categories_retrieval"] == []
    assert trace["input_pii_detected"] is False
    assert trace["input_pii_categories"] == []


def test_real_question_invokes_retrieval(monkeypatch):
    """Pergunta real deve chamar retrieval."""
    chunks = [
        {"content": "O SLA do plano Basico e 99.5%.", "source": "sla.md"},
    ]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))
    spy_classifier = MagicMock(return_value=True)
    monkeypatch.setattr(intent_classifier, "classify", spy_classifier)

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("O SLA e 99.5%.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o SLA do plano Basico?", "session_id": "session-real-q"}
    )

    assert response.status_code == 200
    data = response.json()
    trace = data["trace"]
    assert trace["rag_used"] is True
    assert trace["intent_skipped_retrieval"] is False
    assert trace["retrieved_count"] == 1


def test_ambiguous_message_invokes_intent_classifier(monkeypatch):
    """Mensagem inconclusiva pela heuristica dispara classificador."""
    assert not _is_obvious_non_question("O plano X cobre integracao Slack?")

    chunks = [{"content": "Integracoes nativas incluem Slack.", "source": "integracoes.md"}]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))
    spy_classifier = MagicMock(return_value=True)
    monkeypatch.setattr(intent_classifier, "classify", spy_classifier)

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Sim.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "O plano X cobre integracao Slack?", "session_id": "session-ambig"}
    )

    assert response.status_code == 200
    spy_classifier.assert_called_once()
    assert response.json()["trace"]["rag_used"] is True


def test_intent_classifier_failure_defaults_to_retrieval(monkeypatch):
    """Falha do classificador = fallback conservador = retrieval."""
    assert not _is_obvious_non_question("Mensagem maior que 12 chars e 3 palavras.")

    chunks = [{"content": "qualquer coisa", "source": "x.md"}]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))
    monkeypatch.setattr(
        intent_classifier,
        "classify",
        MagicMock(side_effect=RuntimeError("classifier down")),
    )

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("OK", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Mensagem maior que 12 chars e 3 palavras.", "session_id": "session-fail"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["rag_used"] is True


def test_classifier_returns_false_skips_retrieval(monkeypatch):
    """Quando classificador retorna False, retrieval e pulado mesmo apos heuristica inconclusiva."""
    assert not _is_obvious_non_question("Talvez eu queira saber sobre alguma coisa")

    spy_retrieve = MagicMock(return_value=[])
    monkeypatch.setattr(retriever, "retrieve", spy_retrieve)
    spy_classifier = MagicMock(return_value=False)
    monkeypatch.setattr(intent_classifier, "classify", spy_classifier)

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Como posso ajudar?", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Talvez eu queira saber sobre alguma coisa", "session_id": "session-conv"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["rag_used"] is False
    assert trace["intent_skipped_retrieval"] is True
    spy_retrieve.assert_not_called()
    spy_classifier.assert_called_once()


def test_trace_pii_separates_retrieval_from_response(monkeypatch):
    """Chunks com R$ vao para pii_categories_retrieval; resposta limpa -> pii_categories vazio."""
    chunks_with_pi = [
        {"content": "O plano Basico custa R$ 49,90 por mes.", "source": "planos.md"},
        {"content": "O SLA e 99.5%.", "source": "sla.md"},
    ]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks_with_pi))

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("O SLA e 99.5%.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o SLA do plano Basico?", "session_id": "session-pii-sep"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "entregue"
    assert trace["pii_categories"] == []
    assert "R$" in trace["pii_categories_retrieval"]
    assert trace["blocked_count"] == 1
    assert trace["used_count"] == 1


def test_trace_pii_response_populated_when_judge_blocks(monkeypatch):
    """Quando judge detecta PII na resposta, pii_categories e populado."""
    chunks = [{"content": "O SLA e 99.5%.", "source": "sla.md"}]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))

    leaked_response = "O CPF do usuario e 123.456.789-00."
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=(leaked_response, None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="SIM"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o CPF do usuario?", "session_id": "session-judge-block"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "bloqueado-na-saida"
    assert "CPF" in trace["pii_categories"]


def test_nvidia_nim_fallback_provider_is_none_without_key(monkeypatch):
    original_key = providers_module.NVIDIA_NIM_API_KEY
    original_provider = providers_module.nvidia_nim_fallback_provider

    monkeypatch.setattr(providers_module, "NVIDIA_NIM_API_KEY", "")
    monkeypatch.setattr(providers_module, "nvidia_nim_fallback_provider", None)
    monkeypatch.setattr(main_module, "nvidia_nim_fallback_provider", None)

    from app.providers import NvidiaNimProvider

    new_provider = NvidiaNimProvider() if providers_module.NVIDIA_NIM_API_KEY else None
    assert new_provider is None

    monkeypatch.setattr(providers_module, "nvidia_nim_fallback_provider", original_provider)
    monkeypatch.setattr(providers_module, "NVIDIA_NIM_API_KEY", original_key)
    monkeypatch.setattr(main_module, "nvidia_nim_fallback_provider", original_provider)


# ---------------------------------------------------------------------------
# rev 13: input PII hard block + judge_block sentinel + split timings
# ---------------------------------------------------------------------------


def test_input_pii_blocked_before_llm(monkeypatch):
    """CPF no input do usuario: bloqueado antes de LLM/IntentClassifier/retriever."""
    spy_retrieve = MagicMock(return_value=[])
    monkeypatch.setattr(retriever, "retrieve", spy_retrieve)

    spy_generate = MagicMock(return_value=("Nunca deveria ser chamado.", None))
    monkeypatch.setattr(llm_provider, "generate", spy_generate)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "meu cpf e 123.456.789-00", "session_id": "session-input-cpf"}
    )

    assert response.status_code == 200
    body = response.json()
    trace = body["trace"]
    assert body["guardrail_state"] == "bloqueado-na-entrada"
    assert trace["input_pii_detected"] is True
    assert "CPF" in trace["input_pii_categories"]
    assert trace["judge_decision"] == ""
    assert trace["retrieved_count"] == 0
    assert trace["used_count"] == 0
    assert trace["blocked_count"] == 0
    assert trace["rag_used"] is False
    assert "Detectei dados sensiveis" in body["answer"]
    spy_retrieve.assert_not_called()
    spy_generate.assert_not_called()


def test_input_pii_with_email(monkeypatch):
    """Email no input: bloqueado na entrada, categoria email."""
    spy_retrieve = MagicMock(return_value=[])
    spy_generate = MagicMock(return_value=("x", None))
    monkeypatch.setattr(retriever, "retrieve", spy_retrieve)
    monkeypatch.setattr(llm_provider, "generate", spy_generate)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "meu email e teste@example.com", "session_id": "session-input-email"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "bloqueado-na-entrada"
    assert trace["input_pii_detected"] is True
    assert "email" in trace["input_pii_categories"]
    spy_retrieve.assert_not_called()
    spy_generate.assert_not_called()


def test_input_pii_with_currency(monkeypatch):
    """R$ no input: bloqueado na entrada, categoria R$."""
    spy_retrieve = MagicMock(return_value=[])
    spy_generate = MagicMock(return_value=("x", None))
    monkeypatch.setattr(retriever, "retrieve", spy_retrieve)
    monkeypatch.setattr(llm_provider, "generate", spy_generate)

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "ganhei R$ 50.000 esse mes", "session_id": "session-input-currency"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "bloqueado-na-entrada"
    assert trace["input_pii_detected"] is True
    assert "R$" in trace["input_pii_categories"]
    spy_retrieve.assert_not_called()
    spy_generate.assert_not_called()


def test_input_pii_does_not_skip_for_safe_text(monkeypatch):
    """Texto sem PII segue pipeline normal; input_pii_detected fica False."""
    chunks = [{"content": "O SLA e 99.5%.", "source": "sla.md"}]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))
    monkeypatch.setattr(
        llm_provider, "generate", MagicMock(return_value=("Resposta segura.", None))
    )
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Ola, qual o plano?", "session_id": "session-input-safe"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "entregue"
    assert trace["input_pii_detected"] is False
    assert trace["input_pii_categories"] == []


def test_judge_block_sentinel_when_regex_passes(monkeypatch):
    """Judge SIM sem categoria de regex: pii_categories ganha sentinela judge_block."""
    chunks = [{"content": "Contexto limpo.", "source": "x.md"}]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))

    clean_response = "Resposta sem categoria de regex."
    monkeypatch.setattr(
        llm_provider, "generate", MagicMock(return_value=(clean_response, None))
    )
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="SIM"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Pergunta limpa", "session_id": "session-judge-sentinel"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "bloqueado-na-saida"
    assert trace["pii_categories"] == ["judge_block"]
    assert trace["judge_decision"] == "SIM"


def test_judge_block_not_added_when_regex_finds_category(monkeypatch):
    """Quando regex ja categorizou (CPF), judge_block NAO e adicionado."""
    chunks = [{"content": "Contexto limpo.", "source": "x.md"}]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))

    leaked_response = "O CPF do usuario e 123.456.789-00."
    monkeypatch.setattr(
        llm_provider, "generate", MagicMock(return_value=(leaked_response, None))
    )
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="SIM"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o CPF?", "session_id": "session-judge-no-sentinel"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "bloqueado-na-saida"
    assert "judge_block" not in trace["pii_categories"]
    assert "CPF" in trace["pii_categories"]


def test_pii_judge_ms_tracks_judge_only(monkeypatch):
    """pii_judge_ms mede apenas o judge; post_guardrail_ms cobre os dois."""
    chunks = [{"content": "Contexto limpo.", "source": "x.md"}]
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=chunks))

    monkeypatch.setattr(
        llm_provider, "generate", MagicMock(return_value=("Resposta limpa.", None))
    )
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Como funciona?", "session_id": "session-pii-ms"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "entregue"
    assert trace["pii_judge_ms"] >= 0
    assert trace["pii_regex_ms"] >= 0
    assert trace["post_guardrail_ms"] >= trace["pii_judge_ms"]
    assert trace["post_guardrail_ms"] >= trace["pii_regex_ms"]


# ---------------------------------------------------------------------------
# rev 14: Table Editor — endpoint READ-ONLY knowledge_documents
# ---------------------------------------------------------------------------


def test_knowledge_documents_endpoint_returns_schema_and_rows():
    client = TestClient(app)
    response = client.get("/api/admin/knowledge-documents?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert data["total"] >= 1
    assert data["limit"] == 5
    assert data["offset"] == 0
    assert data["table"]["name"] == "knowledge_documents"
    col_names = [c["name"] for c in data["table"]["columns"]]
    assert "id" in col_names
    assert "source" in col_names
    assert "content" in col_names
    assert "embedding" in col_names
    assert "created_at" in col_names
    emb_col = next(c for c in data["table"]["columns"] if c["name"] == "embedding")
    assert emb_col["type"] == "vector(2048)"

    assert len(data["rows"]) >= 1
    first = data["rows"][0]
    assert "id" in first
    assert "source" in first
    assert "content" in first
    assert "embedding_summary" in first
    summary = first["embedding_summary"]
    assert summary["dim"] == 2048
    assert len(summary["first5"]) == 5
    assert len(summary["last5"]) == 5
    assert summary["l2_norm"] > 0


def test_knowledge_documents_endpoint_paginates():
    client = TestClient(app)

    page1 = client.get("/api/admin/knowledge-documents?limit=2&offset=0").json()
    page2 = client.get("/api/admin/knowledge-documents?limit=2&offset=2").json()

    assert page1["total"] == page2["total"]
    assert page1["total"] >= 2
    assert len(page1["rows"]) == 2
    assert len(page2["rows"]) == 2
    assert page1["rows"][0]["id"] != page2["rows"][0]["id"]


def test_knowledge_documents_endpoint_filters_by_source():
    client = TestClient(app)
    response = client.get("/api/admin/knowledge-documents?source=planos.md")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert all(row["source"] == "planos.md" for row in data["rows"])


def test_knowledge_documents_endpoint_limit_clamped():
    client = TestClient(app)
    response = client.get("/api/admin/knowledge-documents?limit=1000")

    assert response.status_code == 422


def test_knowledge_documents_endpoint_returns_empty_for_unknown_source():
    client = TestClient(app)
    response = client.get("/api/admin/knowledge-documents?source=nope-inexistente.md")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["rows"] == []


# ---------------------------------------------------------------------------
# rev 15: preco_publico flag — chunks de catalogo com R$ nao sao bloqueados
# ---------------------------------------------------------------------------


def test_preco_publico_chunk_is_not_blocked_by_regex(monkeypatch):
    """Chunk com preco_publico=True e R$ 49,90 NAO deve ser bloqueado pelo pre-guardrail."""
    preco_chunk = {
        "content": "O plano Basico custa R$ 49,90 por mes e inclui suporte por email.",
        "source": "planos.md",
        "preco_publico": True,
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[preco_chunk]))

    spy_generate = MagicMock(return_value=("O plano Basico custa quarenta e nove reais e noventa centavos por mes.", None))
    monkeypatch.setattr(llm_provider, "generate", spy_generate)
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa o plano basico?", "session_id": "session-preco-pub-1"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "entregue"
    assert trace["retrieved_count"] == 1
    assert trace["blocked_count"] == 0
    assert trace["used_count"] == 1
    spy_generate.assert_called_once()
    sent_prompt = spy_generate.call_args.kwargs["messages"][-1]["content"]
    assert "R$ 49,90" in sent_prompt
    assert "plano Basico" in sent_prompt


def test_preco_publico_chunk_bypasses_r_in_pii_categories(monkeypatch):
    """Chunk com preco_publico=True NAO adiciona R$ em pii_categories_retrieval."""
    preco_chunk = {
        "content": "O plano Profissional custa R$ 99,90 por mes.",
        "source": "planos.md",
        "preco_publico": True,
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[preco_chunk]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Resposta.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa o profissional?", "session_id": "session-preco-pub-2"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "entregue"
    assert "R$" not in trace["pii_categories_retrieval"]
    assert trace["blocked_count"] == 0


def test_preco_publico_false_still_blocks(monkeypatch):
    """Chunk com R$ mas SEM preco_publico (ex.: threshold de faturamento) continua bloqueado."""
    threshold_chunk = {
        "content": "Clientes com faturamento acima de R$ 50.000 mensais tem acesso premium.",
        "source": "onboarding.md",
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[threshold_chunk]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Resposta.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Qual o threshold premium?", "session_id": "session-preco-pub-3"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["blocked_count"] == 1
    assert trace["used_count"] == 0
    assert "R$" in trace["pii_categories_retrieval"]


def test_non_r_categories_still_blocked_in_preco_publico(monkeypatch):
    """preco_publico libera apenas R$; outras categorias (CPF, CNPJ, email) seguem bloqueadas."""
    mixed_chunk = {
        "content": "Plano R$ 49,90 por mes. Contato: suporte@example.com.",
        "source": "planos.md",
        "preco_publico": True,
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[mixed_chunk]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value=("Resposta.", None)))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa o plano e o contato?", "session_id": "session-preco-pub-4"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["blocked_count"] == 1
    assert "email" in trace["pii_categories_retrieval"]
    assert "R$" not in trace["pii_categories_retrieval"]


def test_post_guardrail_allows_r_when_source_chunk_is_preco_publico(monkeypatch):
    """Pos-guardrail: se algum chunk usado tem preco_publico=True, R$ na resposta NAO bloqueia."""
    preco_chunk = {
        "content": "O plano Basico custa R$ 49,90 por mes e inclui suporte por email.",
        "source": "planos.md",
        "preco_publico": True,
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[preco_chunk]))
    monkeypatch.setattr(
        llm_provider, "generate",
        MagicMock(return_value=("O plano Basico custa R$ 49,90 por mes.", None)),
    )
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa o plano basico?", "session_id": "session-preco-pub-5"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "entregue"
    assert trace["blocked_count"] == 0
    assert trace["used_count"] == 1
    assert "R$" in response.json()["answer"]
    assert "R$" not in trace["pii_categories"]


def test_post_guardrail_still_blocks_r_when_no_preco_publico_chunk(monkeypatch):
    """Pos-guardrail: se nenhum chunk usado tem preco_publico, R$ na resposta BLOQUEIA."""
    plain_chunk = {
        "content": "Documento qualquer sem preco publico.",
        "source": "x.md",
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[plain_chunk]))
    monkeypatch.setattr(
        llm_provider, "generate",
        MagicMock(return_value=("O valor e R$ 99,90 por mes.", None)),
    )
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Quanto custa alguma coisa?", "session_id": "session-preco-pub-6"}
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["guardrail_state"] == "bloqueado-na-saida"
    assert "R$" in trace["pii_categories"]
