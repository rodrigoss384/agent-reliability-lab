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
  rag_used?: boolean;
  input_pii_detected?: boolean;
  input_pii_categories?: string[];
  pii_categories?: string[];
  pii_categories_retrieval?: string[];
  judge_decision?: string;
  judge_model?: string;
  primary_model?: string;
  fallback_used?: boolean;
  pre_guardrail_ms?: number;
  llm_ms?: number;
  post_guardrail_ms?: number;
  pii_regex_ms?: number;
  pii_judge_ms?: number;
  rate_limit_reason?: string;
  intent_skipped_retrieval?: boolean;
  embedding_provider?: string;
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
    if (res.status === 429) {
      const body = await res.json().catch(() => null);
      if (body && body.guardrail_state) {
        return body as ApiChatResponse;
      }
    }
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

export interface EmbeddingSummary {
  dim: number;
  l2_norm: number;
  min: number;
  max: number;
  mean: number;
  first5: number[];
  last5: number[];
}

export interface ColumnDescriptor {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
}

export interface KnowledgeDocumentRow {
  id: string;
  source: string;
  content: string;
  embedding_summary: EmbeddingSummary;
  preco_publico: boolean;
  created_at: string | null;
}

export interface TableDescriptor {
  name: string;
  columns: ColumnDescriptor[];
}

export interface KnowledgeDocumentsResponse {
  total: number;
  limit: number;
  offset: number;
  table: TableDescriptor;
  rows: KnowledgeDocumentRow[];
}

export async function getKnowledgeDocuments(
  limit = 20,
  offset = 0,
  source?: string,
): Promise<KnowledgeDocumentsResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (source) params.set("source", source);
  const res = await fetch(`${API_BASE}/api/admin/knowledge-documents?${params.toString()}`);
  if (!res.ok) {
    throw new ApiRequestError(res.status, `Failed to load knowledge_documents (${res.status})`);
  }
  return res.json();
}
