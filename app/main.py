import re
import time

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="RAG PII Guardrails API", version="0.1.0")

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

# Mock LLM provider client / service
class LLMProvider:
    def generate(self, prompt: str, model: str) -> str:
        return f"Response to: {prompt[:30]}"

llm_provider = LLMProvider()

# Mock retriever
class Retriever:
    def retrieve(self, question: str, limit: int = 5) -> list[dict]:
        return []

retriever = Retriever()


def is_sensitive(content: str) -> bool:
    # 1. Valor monetário com R$
    if re.search(r"R\$\s*\d+", content):
        return True
    # 2. CPF (e.g. 000.000.000-00)
    if re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", content):
        return True
    # 3. CNPJ (e.g. 12.345.678/0001-99)
    if re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", content):
        return True
    # 4. Email
    return bool(re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", content))

@app.post("/api/chat")
def create_chat(request: ChatRequest):
    start_time = time.perf_counter()
    
    session_id = request.session_id or "session-default"
    
    # Retrieve documents
    chunks = retriever.retrieve(request.question, limit=5)
    retrieved_count = len(chunks)
    
    used_chunks = []
    blocked_count = 0
    
    for chunk in chunks:
        if is_sensitive(chunk.get("content", "")):
            blocked_count += 1
        else:
            used_chunks.append(chunk)
            
    used_count = len(used_chunks)
    
    # Determine state and response
    if retrieved_count > 0 and used_count == 0:
        guardrail_state = "bloqueado-na-entrada"
        answer = "Desculpe, o conteúdo necessário para responder foi bloqueado por conter dados sensíveis."
    else:
        # Build prompt with remaining allowed chunks
        context = "\n".join([chunk["content"] for chunk in used_chunks])
        prompt = f"Question: {request.question}\nContext: {context}"
        # Call provider
        answer = llm_provider.generate(prompt, model="gemini-1.5-flash")
        guardrail_state = "entregue"
        
    total_ms = int((time.perf_counter() - start_time) * 1000)
    
    # Prepare response
    trace = Trace(
        retrieved_count=retrieved_count,
        used_count=used_count,
        blocked_count=blocked_count,
        guardrail_state=guardrail_state,
        total_ms=total_ms,
        sources=[chunk.get("source", "unknown") for chunk in used_chunks]
    )
    
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        model_used="gemini-1.5-flash",
        guardrail_state=guardrail_state,
        trace=trace
    )

@app.get("/api/health")
def get_health():
    return {"status": "healthy", "components": {"database": "available", "redis": "available"}}

@app.get("/api/models")
def get_models():
    return {"primary_model": "gemini-1.5-flash", "fallback_model": "gemini-1.5-pro"}

@app.get("/api/conversation/{session_id}")
def get_conversation(session_id: str):
    return {"session_id": session_id, "turns": []}
