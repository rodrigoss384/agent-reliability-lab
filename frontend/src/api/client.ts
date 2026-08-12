const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export interface ApiChatResponse {
  session_id: string;
  answer: string;
  model_used: string;
  guardrail_state: string;
  trace: ApiTrace;
}

export interface ApiTrace {
  retrieved_count: number;
  used_count: number;
  blocked_count: number;
  guardrail_state: string;
  total_ms: number;
  sources: string[];
}

export interface ApiConversationTurn {
  question: string;
  answer: string;
  model_used: string;
  guardrail_state: string;
  trace: ApiTrace;
  timestamp: string;
}

export interface ApiConversationResponse {
  session_id: string;
  created_at: number;
  turns: ApiConversationTurn[];
}

export interface ApiError {
  detail: string;
  session_id?: string;
}

export async function postChat(question: string, sessionId?: string): Promise<ApiChatResponse> {
  const body: Record<string, string> = { question };
  if (sessionId) body.session_id = sessionId;

  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => ({ detail: "Unknown error" }))) as ApiError;
    throw new ApiRequestError(res.status, err.detail, err.session_id);
  }

  return res.json();
}

export async function getConversation(sessionId: string): Promise<ApiConversationResponse> {
  const res = await fetch(`${API_BASE}/api/conversation/${sessionId}`);

  if (res.status === 404) {
    throw new ApiRequestError(404, "Sessao nao encontrada ou expirada");
  }

  if (!res.ok) {
    const err = (await res.json().catch(() => ({ detail: "Unknown error" }))) as ApiError;
    throw new ApiRequestError(res.status, err.detail);
  }

  return res.json();
}

export class ApiRequestError extends Error {
  status: number;
  sessionId?: string;

  constructor(status: number, message: string, sessionId?: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.sessionId = sessionId;
  }
}
