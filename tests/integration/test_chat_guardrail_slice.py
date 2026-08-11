from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app, llm_provider, retriever


def test_sensitive_retrieved_chunk_is_excluded_before_provider(monkeypatch):
    # 1. Setup mock retriever to return a permitted chunk and a sensitive chunk (chunk-armadilha)
    permitted_chunk = {
        "content": "SaaS billing cycle is monthly.",
        "source": "billing_doc.txt"
    }
    sensitive_chunk = {
        "content": "Client Acme Corp CNPJ: 12.345.678/0001-99, email: contact@acme.com, renewal 2026-12-31, value R$ 15000.",
        "source": "acme_contract.txt"
    }
    
    mock_retrieve = MagicMock(return_value=[permitted_chunk, sensitive_chunk])
    monkeypatch.setattr(retriever, "retrieve", mock_retrieve)
    
    # 2. Setup LLM provider spy/mock
    spy_generate = MagicMock(return_value="Mocked LLM generation response.")
    monkeypatch.setattr(llm_provider, "generate", spy_generate)
    
    # 3. Call the API endpoint
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"question": "Tell me about contracts and billing", "session_id": "session-test"}
    )
    
    # 4. Assert response is successful
    assert response.status_code == 200
    data = response.json()
    
    # Check trace structure
    trace = data["trace"]
    assert trace["retrieved_count"] == 2
    
    # Oráculo: O guardrail deve ter filtrado o chunk sensível
    # No primeiro RED, essas asserções devem falhar porque a lógica de exclusão não foi implementada
    assert trace["blocked_count"] > 0, "No chunks were blocked by the guardrail"
    assert trace["used_count"] < trace["retrieved_count"], "Used count should be less than retrieved count"
    
    # E o provider spy não pode ter recebido o conteúdo do chunk bloqueado
    assert spy_generate.called, "LLM provider was not called"
    called_prompt = spy_generate.call_args[0][0]
    
    # Verify sensitive data was excluded from the prompt sent to the LLM
    assert "12.345.678/0001-99" not in called_prompt, "CNPJ reached the provider"
    assert "contact@acme.com" not in called_prompt, "Email reached the provider"
    assert "R$ 15000" not in called_prompt, "Value reached the provider"
    assert "acme_contract.txt" not in trace["sources"], "Blocked source was exposed in trace"
