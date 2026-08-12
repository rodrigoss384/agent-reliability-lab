import React, { useState, useRef, useEffect } from "react";
import {
  postChat,
  getConversation,
  type ApiChatResponse,
  type ApiConversationResponse,
  ApiRequestError,
} from "../../api/client";

type AppState = "empty" | "processing" | "bloqueado" | "entregue" | "bloqueado-na-saida" | "falha-segura";

function mapGuardrailState(apiState: string): AppState {
  switch (apiState) {
    case "bloqueado-na-entrada": return "bloqueado";
    case "entregue": return "entregue";
    case "bloqueado-na-saida": return "bloqueado-na-saida";
    case "falha-segura": return "falha-segura";
    default: return "empty";
  }
}

function statusLabel(state: AppState): string {
  switch (state) {
    case "bloqueado": return "BLOCKED";
    case "entregue": return "ENTREGUE";
    case "bloqueado-na-saida": return "BLOCKED_OUTPUT";
    case "falha-segura": return "SAFE_FAILURE";
    default: return "";
  }
}

function guardrailPhase(state: AppState): string {
  switch (state) {
    case "bloqueado": return "pre_guardrail";
    case "entregue": return "post_guardrail";
    case "bloqueado-na-saida": return "post_guardrail";
    case "falha-segura": return "guardrail";
    default: return "";
  }
}

function statusColor(state: AppState): string {
  switch (state) {
    case "bloqueado": return "var(--codeblock-pink)";
    case "bloqueado-na-saida": return "var(--codeblock-orange)";
    case "entregue": return "var(--codeblock-green)";
    case "falha-segura": return "var(--codeblock-red)";
    default: return "var(--codeblock-pink)";
  }
}

function liveAnnouncement(state: AppState): string {
  switch (state) {
    case "bloqueado": return "Entrada bloqueada — PII detectada.";
    case "bloqueado-na-saida": return "Resposta bloqueada — PII detectada na saída.";
    case "falha-segura": return "Falha segura — resposta não confiável.";
    case "entregue": return "Resposta entregue sem PII detectada.";
    default: return "";
  }
}

export default function ChatScreen() {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AppState>("empty");
  const [sentQuestion, setSentQuestion] = useState("");
  const [trace, setTrace] = useState<ApiChatResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [history, setHistory] = useState<ApiConversationResponse | null>(null);
  const [historyState, setHistoryState] = useState<"idle" | "loaded" | "expired" | "loading">("idle");

  const statusRef = useRef<HTMLDivElement>(null);

  const resultStates: AppState[] = ["bloqueado", "entregue", "bloqueado-na-saida", "falha-segura"];

  useEffect(() => {
    if (resultStates.includes(state) && statusRef.current) {
      statusRef.current.focus();
    }
  }, [state]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    setState("processing");
    setSentQuestion(question);
    setHistoryState("idle");
    setHistory(null);

    try {
      const response = await postChat(question, sessionId ?? undefined);
      setSessionId(response.session_id);
      setState(mapGuardrailState(response.guardrail_state));
      setTrace(response);
      setQuestion("");
    } catch {
      setState("falha-segura");
      setTrace({
        session_id: sessionId || "",
        answer: "Desculpe, ocorreu uma falha inesperada no pipeline.",
        model_used: "",
        guardrail_state: "falha-segura",
        trace: {
          retrieved_count: 0,
          used_count: 0,
          blocked_count: 0,
          guardrail_state: "falha-segura",
          total_ms: 0,
          sources: [],
        },
      });
    }
  };

  const handleLoadHistory = async () => {
    if (!sessionId) return;
    setHistoryState("loading");
    try {
      const data = await getConversation(sessionId);
      setHistory(data);
      setHistoryState("loaded");
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 404) {
        setHistoryState("expired");
      } else {
        setHistoryState("expired");
      }
    }
  };

  return (
    <main className="bancada-layout min-h-screen p-8">
      <style>{`
        :root {
          --color-graphite: #17202A;
          --color-paper: #F4F1E8;
          --color-cobalt: #3D6DFF;
          --color-moss: #6EA67A;
          --color-oxide: #CF6855;
          --semantic-canvas: var(--color-graphite);
          --semantic-surface: #202B36;
          --semantic-text: var(--color-paper);
          --semantic-muted: #B7C0C8;
          --semantic-action: var(--color-cobalt);

          --codeblock-bg: #282A36;
          --codeblock-line: #44475A;
          --codeblock-fg: #F8F8F2;
          --codeblock-comment: #6272A4;
          --codeblock-cyan: #8BE9FD;
          --codeblock-green: #50FA7B;
          --codeblock-orange: #FFB86C;
          --codeblock-pink: #FF79C6;
          --codeblock-purple: #BD93F9;
          --codeblock-red: #FF5555;
          --codeblock-yellow: #F1FA8C;
        }

        .bancada-layout {
          background-color: var(--semantic-canvas);
          color: var(--semantic-text);
          font-family: ui-sans-serif, system-ui, sans-serif;
        }

        .text-page-title {
          font-size: 24px;
          font-weight: 700;
          line-height: 1.2;
          color: var(--semantic-text);
        }

        .text-section-title {
          font-size: 18px;
          font-weight: 600;
          line-height: 1.3;
          color: var(--semantic-text);
        }

        .text-body {
          font-size: 16px;
          font-weight: 400;
          line-height: 1.5;
        }

        .text-body-strong {
          font-size: 16px;
          font-weight: 600;
          line-height: 1.5;
        }

        .text-label {
          font-size: 14px;
          font-weight: 600;
          line-height: 1.3;
        }

        .bg-surface {
          background-color: var(--semantic-surface);
        }

        .border-surface {
          border-color: var(--semantic-surface);
        }

        .bg-action {
          background-color: var(--semantic-action);
        }
      `}</style>

      <header className="border-b border-surface pb-4 mb-6">
        <h1 className="text-page-title">Guardrails RAG</h1>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 flex flex-col gap-6" aria-labelledby="conversa-title">
          <h2 id="conversa-title" className="text-section-title">Conversa</h2>

          <div className="flex flex-col gap-4 min-h-[200px]" aria-live="polite">
            {state === "empty" && (
              <p className="text-body text-[var(--semantic-muted)]">
                Envie uma pergunta para testar os guardrails de PII no pipeline RAG.
              </p>
            )}

            {state === "processing" && (
              <p className="text-body text-[var(--semantic-muted)]">
                Processando pergunta no pipeline RAG...
              </p>
            )}

            {resultStates.includes(state) && trace && (
              <div className="flex flex-col gap-4">
                <div className="p-4 bg-surface rounded-lg">
                  <p className="text-label text-[var(--semantic-muted)] mb-1">Você</p>
                  <p className="text-body">{sentQuestion}</p>
                </div>

                <div
                  ref={statusRef}
                  id="guardrail-status"
                  data-testid="guardrail-status"
                  tabIndex={-1}
                  className="p-4 rounded-lg border font-mono text-sm focus:outline-none focus:ring-2 focus:ring-[var(--codeblock-cyan)]"
                  style={{
                    backgroundColor: "var(--codeblock-bg)",
                    borderColor: "var(--codeblock-line)",
                  }}
                >
                  <span className="sr-only">{liveAnnouncement(state)}</span>
                  <div className="flex items-center gap-2 mb-2 select-none">
                    <span style={{ color: "var(--codeblock-comment)" }}>$</span>
                    <span style={{ color: "var(--codeblock-cyan)" }}>guardrail</span>
                    <span style={{ color: "var(--codeblock-fg)" }}>::</span>
                    <span style={{ color: statusColor(state), fontWeight: 600 }}>
                      {guardrailPhase(state)}
                    </span>
                    <span style={{ color: "var(--codeblock-comment)" }}>()</span>
                    <span style={{ color: "var(--codeblock-fg)" }}>{"{"}</span>
                  </div>
                  <div className="ml-4 flex flex-col gap-1">
                    <div>
                      <span style={{ color: "var(--codeblock-purple)" }}>  status</span>
                      <span style={{ color: "var(--codeblock-fg)" }}>:</span>
                      <span style={{ color: statusColor(state) }}> {statusLabel(state)}</span>
                      <span style={{ color: "var(--codeblock-comment)" }}>,</span>
                    </div>
                    <div>
                      <span style={{ color: "var(--codeblock-purple)" }}>  chunks_used</span>
                      <span style={{ color: "var(--codeblock-fg)" }}>:</span>
                      <span style={{ color: "var(--codeblock-cyan)" }}> {trace.trace.used_count}</span>
                      <span style={{ color: "var(--codeblock-comment)" }}>,</span>
                    </div>
                    {state === "bloqueado" && (
                      <div>
                        <span style={{ color: "var(--codeblock-purple)" }}>  reason</span>
                        <span style={{ color: "var(--codeblock-fg)" }}>:</span>
                        <span style={{ color: "var(--codeblock-green)" }}> &quot;todos os chunks recuperados continham PII&quot;</span>
                      </div>
                    )}
                    {state === "entregue" && (
                      <div>
                        <span style={{ color: "var(--codeblock-purple)" }}>  model</span>
                        <span style={{ color: "var(--codeblock-fg)" }}>:</span>
                        <span style={{ color: "var(--codeblock-green)" }}> &quot;{trace.model_used}&quot;</span>
                        <span style={{ color: "var(--codeblock-comment)" }}>,</span>
                      </div>
                    )}
                    <div>
                      <span style={{ color: "var(--codeblock-purple)" }}>  total_ms</span>
                      <span style={{ color: "var(--codeblock-fg)" }}>:</span>
                      <span style={{ color: "var(--codeblock-cyan)" }}> {trace.trace.total_ms}</span>
                    </div>
                  </div>
                  <div className="mt-1">
                    <span style={{ color: "var(--codeblock-fg)" }}>{"}"}</span>
                  </div>
                </div>

                {state === "entregue" && trace.answer && (
                  <div className="p-4 bg-surface rounded-lg">
                    <p className="text-label text-[var(--semantic-muted)] mb-1">Assistente</p>
                    <p className="text-body">{trace.answer}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {sessionId && historyState === "idle" && (
            <button
              type="button"
              data-testid="load-history-btn"
              onClick={handleLoadHistory}
              className="text-label text-[var(--color-cobalt)] hover:underline self-start mt-2"
            >
              Carregar histórico
            </button>
          )}

          {historyState === "loading" && (
            <p className="text-body text-[var(--semantic-muted)]">Carregando histórico...</p>
          )}

          {historyState === "loaded" && history && (
            <div data-testid="history-section" className="flex flex-col gap-3">
              <h3 className="text-label text-[var(--semantic-muted)]">
                Histórico da sessão
              </h3>
              {history.turns.map((turn, i) => (
                <div key={i} className="p-3 bg-surface rounded-lg">
                  <p className="text-[12px] text-[var(--semantic-muted)] mb-1">
                    {turn.timestamp} — {turn.guardrail_state} — {turn.trace.total_ms}ms
                  </p>
                  <p className="text-body-strong text-sm">{turn.question}</p>
                  <p className="text-body text-sm">{turn.answer}</p>
                </div>
              ))}
            </div>
          )}

          {historyState === "expired" && (
            <div
              data-testid="partial-state"
              className="p-4 bg-surface rounded-lg border border-[var(--color-oxide)] mt-4"
            >
              <p className="text-body-strong text-[var(--color-oxide)]">
                Sessão expirou — o histórico não está mais disponível.
              </p>
              <p className="text-body text-[var(--semantic-muted)] mt-1">
                Envie uma nova pergunta para iniciar outra sessão.
              </p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-2 mt-auto">
            <label htmlFor="question" className="text-label">
              Pergunta
            </label>
            <textarea
              id="question"
              value={question}
              onChange={(e) => {
                setQuestion(e.target.value);
              }}
              disabled={state === "processing"}
              className="p-3 rounded bg-surface border border-surface focus:outline-none focus:border-[var(--color-cobalt)] w-full resize-none h-24"
              placeholder="Ex: Qual é o saldo da conta do João Silva, CPF 123.456.789-00?"
              required
            />
            <button
              type="submit"
              disabled={state === "processing" || !question.trim()}
              className="bg-action text-white py-2 px-4 rounded font-semibold self-end hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {state === "processing" ? "Enviando..." : "Enviar"}
            </button>
          </form>
        </section>

        {trace && (
          <section
            data-testid="trace-section"
            className="lg:col-span-1 flex flex-col gap-4"
            aria-labelledby="trace-title"
          >
            <div
              className="p-4 rounded-lg border font-mono text-sm"
              style={{
                backgroundColor: "var(--codeblock-bg)",
                borderColor: "var(--codeblock-line)",
              }}
            >
              <h2
                id="trace-title"
                data-testid="trace-title"
                className="text-[11px] uppercase tracking-wider mb-3 select-none"
                style={{ color: "var(--codeblock-comment)" }}
              >
                /* evidencia_sanitizada */
              </h2>

              <div className="flex gap-2">
                <div
                  className="flex-1 p-2 rounded text-center border"
                  style={{ borderColor: "var(--codeblock-line)" }}
                >
                  <div className="text-[10px] mb-1" style={{ color: "var(--codeblock-comment)" }}>
                    retrieved
                  </div>
                  <div
                    data-testid="metric-retrieved"
                    className="text-lg font-semibold"
                    style={{ color: "var(--codeblock-purple)" }}
                  >
                    {trace.trace.retrieved_count}
                  </div>
                </div>
                <div
                  className="flex-1 p-2 rounded text-center border"
                  style={{ borderColor: "var(--codeblock-line)" }}
                >
                  <div className="text-[10px] mb-1" style={{ color: "var(--codeblock-comment)" }}>
                    blocked
                  </div>
                  <div
                    data-testid="metric-blocked"
                    className="text-lg font-semibold"
                    style={{ color: "var(--codeblock-pink)" }}
                  >
                    {trace.trace.blocked_count}
                  </div>
                </div>
                <div
                  className="flex-1 p-2 rounded text-center border"
                  style={{ borderColor: "var(--codeblock-line)" }}
                >
                  <div className="text-[10px] mb-1" style={{ color: "var(--codeblock-comment)" }}>
                    used
                  </div>
                  <div
                    data-testid="metric-used"
                    className="text-lg font-semibold"
                    style={{ color: "var(--codeblock-purple)" }}
                  >
                    {trace.trace.used_count}
                  </div>
                </div>
              </div>
            </div>

            {trace.trace.sources.length > 0 && (
              <div
                className="p-4 rounded-lg border font-mono text-sm"
                style={{
                  backgroundColor: "var(--codeblock-bg)",
                  borderColor: "var(--codeblock-line)",
                }}
              >
                <h3
                  className="text-[11px] uppercase tracking-wider mb-3 select-none"
                  style={{ color: "var(--codeblock-comment)" }}
                >
                  /* sources */
                </h3>
                <div className="flex flex-col gap-2">
                  {trace.trace.sources.map((source, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span style={{ color: "var(--codeblock-comment)" }}>
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span style={{ color: "var(--codeblock-cyan)" }}>
                        {source}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div
              className="p-4 rounded-lg border font-mono text-sm"
              style={{
                backgroundColor: "var(--codeblock-bg)",
                borderColor: "var(--codeblock-line)",
              }}
            >
              <h3
                className="text-[11px] uppercase tracking-wider mb-3 select-none"
                style={{ color: "var(--codeblock-comment)" }}
              >
                /* pipeline_info */
              </h3>
              <div className="flex flex-col gap-2">
                <div>
                  <span style={{ color: "var(--codeblock-comment)" }}>01</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-cyan)" }}>guardrail_state</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-comment)" }}>→</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-green)" }}>{trace.guardrail_state}</span>
                </div>
                <div>
                  <span style={{ color: "var(--codeblock-comment)" }}>02</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-cyan)" }}>model</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-comment)" }}>→</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-green)" }}>{trace.model_used}</span>
                </div>
                <div>
                  <span style={{ color: "var(--codeblock-comment)" }}>03</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-cyan)" }}>total_ms</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-comment)" }}>→</span>
                  {" "}
                  <span style={{ color: "var(--codeblock-green)" }}>{trace.trace.total_ms}ms</span>
                </div>
              </div>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
