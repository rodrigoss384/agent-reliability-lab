import React, { useState, useRef, useEffect, useCallback } from "react";
import TableEditor from "./TableEditor";
import {
  postChat,
  getConversation,
  type ApiTrace,
} from "../../api/client";

type GuardrailState = "bloqueado" | "entregue" | "bloqueado-na-saida" | "falha-segura" | "limite-cota";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  guardrailState: GuardrailState;
  trace?: ApiTrace;
  modelUsed?: string;
  totalMs?: number;
  ragUsed?: boolean;
  blocked: boolean;
}

const STORAGE_KEY = "rag-pii-chat-session-id";

const SUGGESTED_QUESTIONS = [
  "Como funciona o suporte?",
  "Quais são os planos?",
  "O que é o plano Básico?",
];

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function mapGuardrailState(apiState: string): GuardrailState {
  switch (apiState) {
    case "bloqueado-na-entrada": return "bloqueado";
    case "entregue": return "entregue";
    case "bloqueado-na-saida": return "bloqueado-na-saida";
    case "falha-segura": return "falha-segura";
    case "limite-cota": return "limite-cota";
    default: return "bloqueado";
  }
}

function statusLabel(state: GuardrailState): string {
  switch (state) {
    case "bloqueado": return "BLOCKED";
    case "entregue": return "ENTREGUE";
    case "bloqueado-na-saida": return "BLOCKED_OUTPUT";
    case "falha-segura": return "SAFE_FAILURE";
    case "limite-cota": return "LIMITE_COTA";
  }
}

function emptyAnswerMessage(state: GuardrailState): string {
  switch (state) {
    case "bloqueado": return "Conteúdo bloqueado por conter dados sensíveis.";
    case "bloqueado-na-saida": return "Resposta bloqueada por conter dados sensíveis.";
    case "falha-segura": return "Falha segura — resposta não confiável.";
    case "limite-cota": return "Limite diario gratuito atingido. Configure NVIDIA_NIM_API_KEY para continuar.";
    default: return "";
  }
}

function liveAnnouncement(state: GuardrailState): string {
  switch (state) {
    case "bloqueado": return "Entrada bloqueada — PII detectada.";
    case "bloqueado-na-saida": return "Resposta bloqueada — PII detectada na saída.";
    case "falha-segura": return "Falha segura — resposta não confiável.";
    case "limite-cota": return "Limite de cota atingido no provedor.";
    case "entregue": return "Resposta entregue sem PII detectada.";
  }
}

interface MessageCardProps {
  msg: ChatMessage;
  selected: boolean;
  onSelect: (id: string) => void;
}

function MessageCard({ msg, selected, onSelect }: MessageCardProps) {
  const handleKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(msg.id);
    }
  };
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={() => onSelect(msg.id)}
      onKeyDown={handleKey}
      data-testid={msg.role === "assistant" ? "guardrail-status" : "message-card"}
      data-message-id={msg.id}
      className={`message-card message-${msg.role}${selected ? " message-selected" : ""}`}
    >
      {msg.role === "assistant" && (
        <span className="sr-only">{liveAnnouncement(msg.guardrailState)}</span>
      )}
      <p className="text-label text-muted mb-1">
        {msg.role === "user" ? "Voce" : "Aria"}
      </p>
      <div className="bubble">
        <p className="text-body whitespace-pre-wrap">
          {msg.content || emptyAnswerMessage(msg.guardrailState)}
        </p>
      </div>
      {msg.role === "assistant" && msg.trace && (
        <GuardrailPill state={msg.guardrailState} />
      )}
    </div>
  );
}

function GuardrailPill({ state }: { state: GuardrailState }) {
  const color =
    state === "entregue"
      ? "var(--moss)"
      : state === "bloqueado" || state === "bloqueado-na-saida"
      ? "var(--oxide)"
      : "var(--amber)";
  return (
    <div className="pill mt-2" data-testid="status-pill">
      <span className="pill-dot" style={{ backgroundColor: color }} aria-hidden />
      <span className="pill-text" style={{ color }}>
        {statusLabel(state)}
      </span>
    </div>
  );
}

function MetricsRow({ trace }: { trace: ApiTrace }) {
  return (
    <div className="metrics-row">
      <div className="metric-cell">
        <div className="metric-label">retrieved</div>
        <div data-testid="metric-retrieved" className="metric-value" style={{ color: "var(--cobalt)" }}>
          {trace.retrieved_count}
        </div>
      </div>
      <div className="metric-cell">
        <div className="metric-label">blocked</div>
        <div data-testid="metric-blocked" className="metric-value" style={{ color: "var(--oxide)" }}>
          {trace.blocked_count}
        </div>
      </div>
      <div className="metric-cell">
        <div className="metric-label">used</div>
        <div data-testid="metric-used" className="metric-value" style={{ color: "var(--moss)" }}>
          {trace.used_count}
        </div>
      </div>
    </div>
  );
}

function PiiCategories({ categories }: { categories: string[] }) {
  if (!categories || categories.length === 0) {
    return (
      <div className="pii-row">
        <span className="pii-empty">—</span>
      </div>
    );
  }
  return (
    <div className="pii-row" data-testid="pii-categories">
      {categories.map((cat) => (
        <span key={cat} className="pii-chip" style={{ borderColor: "var(--oxide)", color: "var(--oxide)" }}>
          {cat}
        </span>
      ))}
    </div>
  );
}

interface StageBlockProps {
  index: number;
  title: string;
  rows: Array<{ label: string; value: React.ReactNode; testId?: string }>;
}

function StageBlock({ index, title, rows }: StageBlockProps) {
  return (
    <section className="stage-block" role="region" aria-labelledby={`stage-${index}`}>
      <h4 id={`stage-${index}`} className="stage-heading">
        <span className="stage-num">{String(index).padStart(2, "0")}</span>
        <span className="stage-title">{title}</span>
      </h4>
      <dl className="stage-rows">
        {rows.map((row) => (
          <div key={row.label} className="stage-row">
            <dt className="stage-key">{row.label}</dt>
            <dd className="stage-val" data-testid={row.testId}>
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function SourcesList({ sources }: { sources: string[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <section className="sources-block" aria-label="Sources">
      <h4 className="stage-heading">
        <span className="stage-num">S</span>
        <span className="stage-title">SOURCES</span>
      </h4>
      <ol className="sources-list" data-testid="sources-list">
        {sources.map((s, i) => (
          <li key={`${s}-${i}`} className="source-item">
            <span className="source-num">{String(i + 1).padStart(2, "0")}</span>
            <span className="source-name">{s}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

interface TracePanelProps {
  msg: ChatMessage;
  timestamp: string;
}

function TracePanel({ msg, timestamp }: TracePanelProps) {
  const trace = msg.trace;
  if (!trace) {
    return (
      <aside data-testid="trace-section" className="trace-panel">
        <p className="text-muted text-body">Selecione uma mensagem para ver o trace.</p>
      </aside>
    );
  }
  const fallbackUsed = trace.fallback_used ?? false;
  const primary = trace.primary_model ?? "—";
  const judgeModel = trace.judge_model ?? "—";
  const judgeDecision = trace.judge_decision ?? "—";
  const piiCategories = trace.pii_categories ?? [];
  const piiRetrievalCategories = trace.pii_categories_retrieval ?? [];
  const inputPiiDetected = trace.input_pii_detected ?? false;
  const inputPiiCategories = trace.input_pii_categories ?? [];
  const preMs = trace.pre_guardrail_ms ?? 0;
  const llmMs = trace.llm_ms ?? 0;
  const postMs = trace.post_guardrail_ms ?? 0;
  const piiJudgeMs = trace.pii_judge_ms ?? postMs;
  const ragLabel = trace.rag_used ? "ACIONADO" : "SEM RAG";
  const rateLimitReason = trace.rate_limit_reason ?? "";

  const judgeLabel =
    judgeDecision === "TALVEZ"
      ? "INCONCLUSIVE"
      : judgeDecision === "SIM"
        ? "SIM (bloqueou)"
        : judgeDecision;
  const judgeBlocked = judgeDecision === "SIM";

  return (
    <aside data-testid="trace-section" className="trace-panel" aria-label="Trace detalhado">
      <div className="trace-panel-inner">
        <header className="trace-header">
          <span className="trace-eyebrow">/* TRACE DETAIL */</span>
          <h3 className="trace-title">Evidencia sanitizada</h3>
          <p className="trace-subtitle text-muted">
            Mensagem selecionada: <span className="text-mono">{timestamp}</span>
          </p>
        </header>

        <MetricsRow trace={trace} />

        <div className="rag-row">
          <span className="metric-label">RAG</span>
          <span
            className="rag-state"
            data-testid="rag-indicator"
            style={{ color: trace.rag_used ? "var(--moss)" : "var(--semantic-muted)" }}
          >
            {ragLabel}
          </span>
        </div>

        <StageBlock
          index={1}
          title="RETRIEVAL"
          rows={[
            { label: "retrieved", value: trace.retrieved_count },
            { label: "blocked", value: trace.blocked_count },
            { label: "used", value: trace.used_count },
            { label: "rag", value: ragLabel },
            { label: "sources_count", value: trace.sources.length },
            { label: "duration", value: `${preMs.toLocaleString("pt-BR")} ms` },
          ]}
        />

        <StageBlock
          index={2}
          title="GERACAO"
          rows={[
            { label: "primary", value: <span className="text-mono">{primary}</span> },
            { label: "fallback", value: fallbackUsed ? "usado" : "nao usado" },
            { label: "model_used", value: <span className="text-mono">{msg.modelUsed ?? primary}</span> },
            { label: "llm_ms", value: `${llmMs.toLocaleString("pt-BR")} ms` },
            ...(rateLimitReason ? [{ label: "rate_limit", value: rateLimitReason }] : []),
          ]}
        />

        <StageBlock
          index={3}
          title="OUTPUT GUARDRAIL"
          rows={[
            ...(inputPiiDetected
              ? [
                  {
                    label: "input_pii",
                    value: (
                      <span className="pii-row">
                        <span className="pii-chip" style={{ borderColor: "var(--oxide)", color: "var(--oxide)" }}>
                          BLOQUEADO NA ENTRADA
                        </span>
                      </span>
                    ),
                  },
                  {
                    label: "input_pii_cats",
                    value: <PiiCategories categories={inputPiiCategories} />,
                  },
                ]
              : []),
            {
              label: "pii_regex_resposta",
              value:
                piiCategories.length === 0
                  ? "passou"
                  : piiCategories.includes("judge_block")
                    ? "passou (regex vazio; judge_block)"
                    : "detectou PII",
            },
            {
              label: "pii_regex_retrieval",
              value:
                piiRetrievalCategories.length === 0
                  ? "passou"
                  : `detectou PII em ${piiRetrievalCategories.length} categoria(s)`,
            },
            { label: "pii_judge", value: judgeLabel },
            { label: "pii_judge_model", value: <span className="text-mono">{judgeModel}</span> },
            { label: "pii_judge_ms", value: `${piiJudgeMs.toLocaleString("pt-BR")} ms` },
            ...(msg.guardrailState !== "entregue" || piiCategories.length > 0
              ? [
                  {
                    label: "pii_detected",
                    value: <PiiCategories categories={piiCategories} />,
                  },
                ]
              : []),
            { label: "state", value: statusLabel(msg.guardrailState) },
          ]}
        />

        <SourcesList sources={trace.sources} />

        <div className="total-block" data-testid="total-block">
          <span className="total-label">total_ms</span>
          <span className="total-value text-mono">{(msg.totalMs ?? trace.total_ms ?? 0).toLocaleString("pt-BR")} ms</span>
        </div>
      </div>
    </aside>
  );
}

export default function ChatScreen() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [historyState, setHistoryState] = useState<"idle" | "loaded" | "expired" | "loading">("idle");
  const [hasLoadedFromStorage, setHasLoadedFromStorage] = useState(false);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [mobileTraceOpen, setMobileTraceOpen] = useState(false);
  const [showTableEditor, setShowTableEditor] = useState(false);
  const [timestamps, setTimestamps] = useState<Record<string, string>>({});

  const statusRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isProcessing, scrollToBottom]);

  const loadConversationFromStorage = useCallback(async (sid: string) => {
    setHistoryState("loading");
    try {
      const data = await getConversation(sid);
      const restoredMessages: ChatMessage[] = [];
      const ts: Record<string, string> = {};
      for (const turn of data.turns) {
        const userId = generateId();
        const assistantId = generateId() + "-a";
        restoredMessages.push({
          id: userId,
          role: "user",
          content: turn.question,
          guardrailState: "entregue",
          blocked: false,
        });
        restoredMessages.push({
          id: assistantId,
          role: "assistant",
          content: turn.answer,
          guardrailState: "entregue",
          trace: turn.trace,
          modelUsed: turn.model_used,
          totalMs: turn.trace.total_ms,
          ragUsed: turn.trace.rag_used,
          blocked: false,
        });
        ts[userId] = turn.timestamp;
        ts[assistantId] = turn.timestamp;
      }
      setMessages(restoredMessages);
      setTimestamps(ts);
      if (restoredMessages.length > 0) {
        const last = restoredMessages[restoredMessages.length - 1];
        setSelectedMessageId(last.id);
      }
      setHistoryState("loaded");
    } catch {
      localStorage.removeItem(STORAGE_KEY);
      setSessionId(null);
      setHistoryState("expired");
    }
  }, []);

  useEffect(() => {
    if (hasLoadedFromStorage) return;
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      setSessionId(stored);
      loadConversationFromStorage(stored);
    }
    setHasLoadedFromStorage(true);
  }, [hasLoadedFromStorage, loadConversationFromStorage]);

  const sendMessage = useCallback(
    async (override?: string) => {
      const trimmed = (override ?? question).trim();
      if (!trimmed || isProcessing) return;

      const userMsg: ChatMessage = {
        id: generateId(),
        role: "user",
        content: trimmed,
        guardrailState: "bloqueado",
        blocked: false,
      };
      const userTs = new Date().toISOString().replace("T", " ").slice(0, 19);
      setMessages((prev) => [...prev, userMsg]);
      setTimestamps((prev) => ({ ...prev, [userMsg.id]: userTs }));
      if (!override) setQuestion("");
      setIsProcessing(true);
      setSelectedMessageId(userMsg.id);
      setMobileTraceOpen(false);

      try {
        const response = await postChat(trimmed, sessionId ?? undefined);
        setSessionId(response.session_id);
        localStorage.setItem(STORAGE_KEY, response.session_id);

        const gState = mapGuardrailState(response.guardrail_state);
        const assistantId = generateId() + "-a";
        const assistantTs = new Date().toISOString().replace("T", " ").slice(0, 19);
        const assistantMsg: ChatMessage = {
          id: assistantId,
          role: "assistant",
          content: response.guardrail_state === "entregue" ? response.answer : "",
          guardrailState: gState,
          trace: response.trace,
          modelUsed: response.model_used,
          totalMs: response.trace.total_ms,
          ragUsed: response.trace.rag_used,
          blocked: gState !== "entregue",
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setTimestamps((prev) => ({ ...prev, [assistantId]: assistantTs }));
        setSelectedMessageId(assistantId);
        statusRef.current?.focus();
      } catch (err) {
        const fallbackTrace: ApiTrace = {
          retrieved_count: 0,
          used_count: 0,
          blocked_count: 0,
          guardrail_state: "falha-segura",
          total_ms: 0,
          sources: [],
          rag_used: false,
        };
        const assistantId = generateId() + "-a";
        const assistantTs = new Date().toISOString().replace("T", " ").slice(0, 19);
        const assistantMsg: ChatMessage = {
          id: assistantId,
          role: "assistant",
          content: "",
          guardrailState: "falha-segura",
          trace: fallbackTrace,
          blocked: true,
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setTimestamps((prev) => ({ ...prev, [assistantId]: assistantTs }));
        setSelectedMessageId(assistantId);
      } finally {
        setIsProcessing(false);
      }
    },
    [question, isProcessing, sessionId],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleNewConversation = () => {
    localStorage.removeItem(STORAGE_KEY);
    setSessionId(null);
    setMessages([]);
    setTimestamps({});
    setSelectedMessageId(null);
    setHistoryState("idle");
    setMobileTraceOpen(false);
  };

  const selectedMessage =
    messages.find((m) => m.id === selectedMessageId) ??
    [...messages].reverse().find((m) => m.role === "assistant") ??
    null;

  const isEmpty = messages.length === 0 && historyState !== "loading";

  return (
    <main className="bancada-layout">
      {showTableEditor && (
        <TableEditor onClose={() => setShowTableEditor(false)} />
      )}
      <style>{`
        :root {
          --color-graphite: #17202A;
          --color-graphite-2: #202B36;
          --color-paper: #F4F1E8;
          --color-cobalt: #3D6DFF;
          --color-moss: #6EA67A;
          --color-oxide: #CF6855;
          --color-amber: #D9A24A;
          --color-paper-2: #E8E3D3;

          --font-serif: "IBM Plex Serif", ui-serif, Georgia, serif;
          --font-sans: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
          --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;

          --bg-canvas: var(--color-graphite);
          --bg-surface: var(--color-graphite-2);
          --bg-surface-2: #283342;
          --fg-text: var(--color-paper);
          --fg-muted: #B7C0C8;
          --fg-action: var(--color-cobalt);
          --border-line: #2F3B48;
        }

        .sr-only {
          position: absolute;
          width: 1px;
          height: 1px;
          padding: 0;
          margin: -1px;
          overflow: hidden;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
          border: 0;
        }

        .bancada-layout {
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          background-color: var(--bg-canvas);
          color: var(--fg-text);
          font-family: var(--font-sans);
        }

        .display {
          font-family: var(--font-serif);
          font-size: 28px;
          font-weight: 700;
          line-height: 1.15;
          letter-spacing: -0.01em;
          color: var(--fg-text);
        }
        .title {
          font-family: var(--font-sans);
          font-size: 18px;
          font-weight: 600;
          line-height: 1.3;
          color: var(--fg-text);
        }
        .text-body { font-family: var(--font-sans); font-size: 15px; font-weight: 400; line-height: 1.55; }
        .text-body-strong { font-family: var(--font-sans); font-size: 15px; font-weight: 600; line-height: 1.55; }
        .text-label { font-family: var(--font-sans); font-size: 12px; font-weight: 600; line-height: 1.3; letter-spacing: 0.04em; text-transform: uppercase; }
        .text-mono { font-family: var(--font-mono); font-size: 12px; font-weight: 500; }
        .text-muted { color: var(--fg-muted); }

        .app-header {
          flex-shrink: 0;
          border-bottom: 1px solid var(--border-line);
          padding: 20px 32px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          background-color: var(--bg-canvas);
        }
        .brand { display: flex; flex-direction: column; gap: 2px; }
        .brand-mark { display: flex; align-items: center; gap: 10px; }
        .brand-logo {
          width: 28px; height: 28px;
          background: linear-gradient(135deg, var(--color-cobalt), var(--color-moss));
          border-radius: 6px;
          position: relative;
        }
        .brand-logo::after {
          content: ""; position: absolute; inset: 6px;
          border: 2px solid var(--color-paper); border-radius: 3px;
          border-top: 0;
        }
        .brand-sub { font-family: var(--font-sans); font-size: 12px; color: var(--fg-muted); letter-spacing: 0.05em; text-transform: uppercase; }
        .header-actions { display: flex; gap: 12px; align-items: center; }
        .btn-secondary {
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          padding: 8px 14px;
          border-radius: 6px;
          background: transparent;
          color: var(--fg-text);
          border: 1px solid var(--border-line);
          cursor: pointer;
          transition: background-color 0.15s ease, border-color 0.15s ease;
        }
        .btn-secondary:hover { background-color: var(--bg-surface); border-color: var(--color-cobalt); }
        .btn-primary {
          font-family: var(--font-sans);
          font-size: 13px;
          font-weight: 600;
          padding: 9px 16px;
          border-radius: 6px;
          background-color: var(--color-cobalt);
          color: var(--color-paper);
          border: 0;
          cursor: pointer;
          transition: opacity 0.15s ease;
        }
        .btn-primary:hover { opacity: 0.9; }
        .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

        .app-body {
          flex: 1;
          display: grid;
          grid-template-columns: 1fr;
          gap: 0;
          min-height: 0;
        }
        @media (min-width: 1024px) {
          .app-body { grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); gap: 24px; padding: 24px 32px; }
        }

        .conversation {
          display: flex;
          flex-direction: column;
          gap: 16px;
          min-height: 0;
          padding: 24px 24px 0;
        }
        @media (min-width: 1024px) { .conversation { padding: 0; } }

        .messages {
          flex: 1;
          overflow-y: auto;
          padding: 4px 4px 12px 4px;
          display: flex;
          flex-direction: column;
          gap: 16px;
          min-height: 0;
        }
        @media (max-width: 1023px) { .messages { min-height: 240px; } }

        .message-card {
          cursor: pointer;
          padding: 12px 14px;
          background-color: var(--bg-surface);
          border: 1px solid var(--border-line);
          border-radius: 10px;
          transition: border-color 0.15s ease, transform 0.12s ease, box-shadow 0.15s ease;
          outline: none;
        }
        .message-card:hover { border-color: var(--color-cobalt); }
        .message-card:focus-visible { border-color: var(--color-cobalt); box-shadow: 0 0 0 3px rgba(61, 109, 255, 0.25); }
        .message-selected {
          border-color: var(--color-cobalt);
          box-shadow: 0 0 0 2px rgba(61, 109, 255, 0.4);
          transform: translateY(-1px);
        }
        .message-user { align-self: flex-end; max-width: 80%; }
        .message-assistant { align-self: flex-start; max-width: 90%; }

        .bubble { color: var(--fg-text); }

        .pill {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 2px 8px;
          border: 1px solid var(--border-line);
          border-radius: 999px;
          font-family: var(--font-mono);
          font-size: 11px;
          font-weight: 500;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          background-color: var(--bg-canvas);
        }
        .pill-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
        .pill-text { letter-spacing: 0.08em; }

        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 14px;
          margin: 24px auto;
          padding: 24px;
          text-align: center;
          max-width: 520px;
        }
        .empty-mark {
          font-family: var(--font-serif);
          font-size: 28px;
          font-weight: 700;
        }
        .empty-suggestions {
          display: flex;
          flex-wrap: wrap;
          justify-content: center;
          gap: 8px;
          margin-top: 4px;
        }
        .chip {
          font-family: var(--font-sans);
          font-size: 13px;
          padding: 8px 12px;
          border: 1px solid var(--border-line);
          border-radius: 999px;
          background-color: var(--bg-surface);
          color: var(--fg-text);
          cursor: pointer;
          transition: border-color 0.15s ease, background-color 0.15s ease;
        }
        .chip:hover { border-color: var(--color-cobalt); background-color: var(--bg-surface-2); }

        .form {
          flex-shrink: 0;
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 16px 24px 24px;
          background-color: var(--bg-canvas);
          border-top: 1px solid var(--border-line);
        }
        @media (min-width: 1024px) { .form { padding: 16px 0 0; border-top: 0; } }
        .form-textarea {
          font-family: var(--font-sans);
          font-size: 15px;
          padding: 12px 14px;
          background-color: var(--bg-surface);
          border: 1px solid var(--border-line);
          border-radius: 8px;
          color: var(--fg-text);
          resize: none;
          min-height: 76px;
          outline: none;
          transition: border-color 0.15s ease;
        }
        .form-textarea:focus { border-color: var(--color-cobalt); }
        .form-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
        }
        .form-hint { font-family: var(--font-sans); font-size: 12px; color: var(--fg-muted); }

        .partial-state {
          padding: 12px 16px;
          background-color: var(--bg-surface);
          border: 1px solid var(--color-oxide);
          border-radius: 8px;
          align-self: center;
          max-width: 520px;
        }

        .processing {
          display: flex;
          gap: 10px;
          align-items: center;
          padding: 10px 14px;
          background-color: var(--bg-surface);
          border: 1px solid var(--border-line);
          border-radius: 10px;
          align-self: flex-start;
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--fg-muted);
        }
        .processing::before {
          content: ""; width: 8px; height: 8px; border-radius: 50%;
          background-color: var(--color-amber);
          animation: pulse 1.2s ease-in-out infinite;
        }
        @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }

        .mobile-toggle {
          display: inline-flex;
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          padding: 6px 10px;
          background: var(--bg-surface);
          color: var(--fg-text);
          border: 1px solid var(--border-line);
          border-radius: 6px;
          cursor: pointer;
        }
        @media (min-width: 1024px) { .mobile-toggle { display: none; } }

        .trace-panel {
          padding: 24px;
          overflow-y: auto;
          background-color: var(--bg-canvas);
        }
        @media (max-width: 1023px) {
          .trace-panel { display: none; padding: 16px; }
          .trace-panel.mobile-open { display: block; }
        }
        @media (min-width: 1024px) {
          .trace-panel {
            position: sticky;
            top: 24px;
            align-self: start;
            max-height: calc(100vh - 48px);
            border-left: 1px solid var(--border-line);
            padding-left: 24px;
          }
        }
        .trace-panel-inner {
          background-color: var(--bg-surface);
          border: 1px solid var(--border-line);
          border-radius: 10px;
          padding: 18px;
          font-family: var(--font-mono);
          font-size: 12px;
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .trace-header { display: flex; flex-direction: column; gap: 4px; }
        .trace-eyebrow {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--color-amber);
          letter-spacing: 0.06em;
          text-transform: uppercase;
        }
        .trace-title {
          font-family: var(--font-serif);
          font-size: 18px;
          font-weight: 700;
          color: var(--fg-text);
          margin: 0;
        }
        .trace-subtitle {
          font-family: var(--font-sans);
          font-size: 12px;
          letter-spacing: 0;
          text-transform: none;
        }

        .metrics-row {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
        }
        .metric-cell {
          padding: 10px;
          border: 1px solid var(--border-line);
          border-radius: 8px;
          background-color: var(--bg-canvas);
          text-align: center;
        }
        .metric-label {
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--fg-muted);
          letter-spacing: 0.06em;
          text-transform: uppercase;
          margin-bottom: 4px;
        }
        .metric-value {
          font-family: var(--font-mono);
          font-size: 20px;
          font-weight: 600;
        }
        .rag-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 10px;
          border: 1px solid var(--border-line);
          border-radius: 8px;
          background-color: var(--bg-canvas);
        }
        .rag-state {
          font-family: var(--font-mono);
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 0.08em;
        }

        .stage-block { display: flex; flex-direction: column; gap: 8px; }
        .stage-heading {
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--fg-muted);
          display: flex;
          align-items: baseline;
          gap: 8px;
          margin: 0;
          border-top: 1px solid var(--border-line);
          padding-top: 10px;
        }
        .stage-num {
          font-family: var(--font-mono);
          color: var(--color-amber);
          font-size: 11px;
        }
        .stage-title { color: var(--fg-text); }
        .stage-rows { margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
        .stage-row {
          display: grid;
          grid-template-columns: 110px 1fr;
          gap: 8px;
          align-items: baseline;
        }
        .stage-key {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--fg-muted);
          text-transform: lowercase;
        }
        .stage-val {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--fg-text);
          margin: 0;
          word-break: break-word;
        }

        .pii-row { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
        .pii-chip {
          font-family: var(--font-mono);
          font-size: 11px;
          padding: 2px 8px;
          border: 1px solid;
          border-radius: 999px;
          letter-spacing: 0.04em;
        }
        .pii-empty { color: var(--fg-muted); font-family: var(--font-mono); font-size: 12px; }

        .sources-block { display: flex; flex-direction: column; gap: 8px; }
        .sources-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
        .source-item {
          display: grid;
          grid-template-columns: 28px 1fr;
          gap: 8px;
          align-items: baseline;
        }
        .source-num { font-family: var(--font-mono); font-size: 11px; color: var(--fg-muted); }
        .source-name { font-family: var(--font-mono); font-size: 12px; color: var(--color-cobalt); }

        .total-block {
          display: flex;
          justify-content: space-between;
          padding: 10px 12px;
          background-color: var(--bg-canvas);
          border: 1px solid var(--border-line);
          border-top: 2px solid var(--color-amber);
          border-radius: 8px;
        }
        .total-label {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--fg-muted);
          letter-spacing: 0.08em;
          text-transform: uppercase;
          font-weight: 700;
        }
        .total-value {
          font-family: var(--font-mono);
          font-size: 14px;
          font-weight: 600;
          color: var(--fg-text);
        }
      `}</style>

      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">
            <span className="brand-logo" aria-hidden />
            <h1 className="display" style={{ margin: 0 }}>Guardrails RAG</h1>
          </div>
          <span className="brand-sub">agent-reliability-lab</span>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setShowTableEditor(true)}
            data-testid="open-table-editor"
          >
            Ver Tabelas de Dados
          </button>
          {messages.length > 0 && (
            <button type="button" className="btn-secondary" onClick={handleNewConversation}>
              Nova conversa
            </button>
          )}
          {selectedMessage && (
            <button
              type="button"
              className="mobile-toggle"
              onClick={() => setMobileTraceOpen((v) => !v)}
              aria-expanded={mobileTraceOpen}
            >
              {mobileTraceOpen ? "Ocultar trace" : "Ver trace"}
            </button>
          )}
        </div>
      </header>

      <div className="app-body">
        <section className="conversation" aria-labelledby="conversa-title">
          <h2 id="conversa-title" className="title">Conversa</h2>

          <div className="messages" aria-live="polite" data-testid="message-list">
            {isEmpty && (
              <div className="empty-state" data-testid="empty-state">
                <div className="empty-mark">Comece por aqui</div>
                <p className="text-body text-muted">
                  Envie uma pergunta para conversar com o agente e testar os guardrails de PII no pipeline RAG.
                </p>
                <div className="empty-suggestions">
                  {SUGGESTED_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      type="button"
                      className="chip"
                      data-testid="suggested-question"
                      onClick={() => sendMessage(q)}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {historyState === "loading" && messages.length === 0 && (
              <p className="text-body text-muted self-center mt-12">
                Carregando conversa anterior...
              </p>
            )}

            {historyState === "expired" && messages.length === 0 && (
              <div data-testid="partial-state" className="partial-state">
                <p className="text-body-strong" style={{ color: "var(--color-oxide)" }}>
                  Sessao anterior expirou.
                </p>
                <p className="text-body text-muted mt-1">
                  Envie uma nova pergunta para iniciar outra conversa.
                </p>
              </div>
            )}

            {messages.map((msg) => (
              <MessageCard
                key={msg.id}
                msg={msg}
                selected={selectedMessageId === msg.id}
                onSelect={(id) => {
                  setSelectedMessageId(id);
                  setMobileTraceOpen(true);
                }}
              />
            ))}

            {isProcessing && (
              <div
                ref={statusRef}
                tabIndex={-1}
                className="processing"
                aria-live="polite"
                data-testid="processing"
              >
                Processando no pipeline RAG...
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSubmit} className="form">
            <label htmlFor="question" className="text-label text-muted">
              Pergunta
            </label>
            <textarea
              ref={textareaRef}
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isProcessing}
              className="form-textarea"
              placeholder="Digite sua mensagem e pressione Enter (ou Shift+Enter para nova linha)"
              aria-label="Campo de mensagem. Enter para enviar, Shift+Enter para nova linha."
              required
            />
            <div className="form-row">
              <span className="form-hint">Enter envia · Shift+Enter nova linha</span>
              <button
                type="submit"
                disabled={isProcessing || !question.trim()}
                className="btn-primary"
              >
                {isProcessing ? "Enviando..." : "Enviar"}
              </button>
            </div>
          </form>
        </section>

        {selectedMessage && (
          <TracePanel
            msg={selectedMessage}
            timestamp={timestamps[selectedMessage.id] ?? "—"}
          />
        )}
      </div>
    </main>
  );
}
