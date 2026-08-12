import threading
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.providers import DependencyUnavailable, fallback_provider, judge, llm_provider, retriever


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

    spy_generate = MagicMock(return_value="Mocked LLM generation response.")
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
    called_prompt = spy_generate.call_args[0][0]

    assert "12.345.678/0001-99" not in called_prompt, "CNPJ reached the provider"
    assert "contact@acme.com" not in called_prompt, "Email reached the provider"
    assert "R$ 15000" not in called_prompt, "Value reached the provider"
    assert "acme_contract.txt" not in trace["sources"], "Blocked source was exposed in trace"


def test_post_guardrail_regex_blocks_response_with_sensitive_data(monkeypatch):
    permitted_chunk = {
        "content": "O plano basico inclui suporte por email com resposta em ate 24h.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))

    spy_primary = MagicMock(return_value="O plano custa R$ 5.000 por mes para empresas.")
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

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="Voce pode entrar em contato pelo chat ou telefone."))

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

    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="A adesao custa 299 reais, sem taxas adicionais."))

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
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="Os dados aparecem no canto superior direito."))
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
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="Relatorio liberado as 18h."))

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
    assert data["guardrail_state"] == "falha-segura"
    assert "relatorio" not in data["answer"].lower() or "Relatorio" not in data["answer"]


def test_regex_guardrail_error_returns_safe_failure(monkeypatch):
    permitted_chunk = {
        "content": "Documento generico.",
        "source": "planos.md"
    }
    monkeypatch.setattr(retriever, "retrieve", MagicMock(return_value=[permitted_chunk]))
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="Resposta segura."))

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

    spy_fallback = MagicMock(return_value="Resposta via fallback com sucesso.")
    monkeypatch.setattr(fallback_provider, "generate", spy_fallback)

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
    assert data["model_used"] == fallback_provider.model

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
    monkeypatch.setattr(fallback_provider, "generate", spy_fallback)

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
        json={"question": "Pergunta qualquer?", "session_id": "session-dep"}
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
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="Resposta segura."))
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
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="X."))

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
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="OK."))
    monkeypatch.setattr(judge, "evaluate", MagicMock(return_value="NAO"))

    client = TestClient(app)

    results = {}

    def first_request():
        resp = client.post("/api/chat", json={"question": "Q1?", "session_id": "lock-s1"})
        results["first"] = (resp.status_code, resp.json())

    t = threading.Thread(target=first_request)
    t.start()
    resolver.wait(timeout=5)
    import time as _t
    _t.sleep(0.1)

    response2 = client.post("/api/chat", json={"question": "Q2?", "session_id": "lock-s1"})
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
    monkeypatch.setattr(llm_provider, "generate", MagicMock(return_value="OK."))
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
