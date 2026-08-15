// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import ChatScreen from "./ChatScreen";

function fillTextareaAndSubmit(container: HTMLElement, text: string) {
  const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
  const form = container.querySelector("form") as HTMLFormElement;
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  nativeValueSetter?.call(textarea, text);
  const tracker = (textarea as any)._valueTracker;
  if (tracker) tracker.setValue("");
  textarea.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
  textarea.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));
  return form;
}

function fillTextareaAndPressEnter(container: HTMLElement, text: string) {
  const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  nativeValueSetter?.call(textarea, text);
  const tracker = (textarea as any)._valueTracker;
  if (tracker) tracker.setValue("");
  textarea.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
  textarea.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));

  const enterEvent = new KeyboardEvent("keydown", {
    key: "Enter",
    shiftKey: false,
    bubbles: true,
    cancelable: true,
  });
  textarea.dispatchEvent(enterEvent);
}

function fillTextareaAndPressShiftEnter(container: HTMLElement, text: string) {
  const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  nativeValueSetter?.call(textarea, text);
  const tracker = (textarea as any)._valueTracker;
  if (tracker) tracker.setValue("");
  textarea.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));

  const shiftEnterEvent = new KeyboardEvent("keydown", {
    key: "Enter",
    shiftKey: true,
    bubbles: true,
    cancelable: true,
  });
  textarea.dispatchEvent(shiftEnterEvent);
}

function apiResponse(overrides: Record<string, unknown> = {}) {
  return {
    session_id: "ses-test",
    answer: "Resposta via API.",
    model_used: "google/gemini-2.0-flash-001",
    guardrail_state: "entregue",
    trace: {
      retrieved_count: 3,
      used_count: 2,
      blocked_count: 1,
      guardrail_state: "entregue",
      total_ms: 1234,
      sources: ["planos.md", "faq.md"],
      rag_used: true,
    },
    ...overrides,
  };
}

function conversationResponse(turns: unknown[] = []) {
  return {
    session_id: "ses-test",
    created_at: 1000000,
    turns,
  };
}

function setupFetch(responseBody: unknown, status = 200) {
  (globalThis as any).fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(responseBody),
  });
}

describe("RAG PII Chat Small Slice", () => {
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    if (container) {
      document.body.removeChild(container);
      container = null;
    }
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("deve renderizar o composer normal e o titulo", async () => {
    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });
    expect(container!.querySelector("h1")?.textContent).toBe("Guardrails RAG");
    expect(container!.querySelector("textarea")).toBeTruthy();
    expect(container!.querySelector("textarea")?.hasAttribute("disabled")).toBe(false);
  });

  it("deve renderizar mensagem de estado empty por padrao", async () => {
    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });
    expect(container!.textContent).toContain("Envie uma pergunta");
  });

  it("deve desabilitar o botao quando o textarea estiver vazio", async () => {
    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });
    const btn = container!.querySelector("button[type=submit]") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("deve mostrar dica de Enter e Shift+Enter junto ao composer", async () => {
    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });
    expect(container!.textContent).toContain("Enter envia");
    expect(container!.textContent).toContain("Shift+Enter");
  });
});

describe("RAG PII Chat Broad Build", () => {
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    if (container) {
      document.body.removeChild(container);
      container = null;
    }
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("AC-RAGPII-020: deve exibir resposta normal entregue com trace sanitizado", async () => {
    setupFetch(apiResponse());

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Qual o plano Basico?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("ENTREGUE");
    expect(container!.textContent).toContain("Resposta via API.");
    expect(container!.querySelector("[data-testid=metric-retrieved]")?.textContent).toBe("3");
    expect(container!.querySelector("[data-testid=metric-blocked]")?.textContent).toBe("1");
    expect(container!.querySelector("[data-testid=metric-used]")?.textContent).toBe("2");
  });

  it("AC-RAGPII-007: deve exibir bloqueio de saida com post-guardrail", async () => {
    setupFetch(apiResponse({
      guardrail_state: "bloqueado-na-saida",
      answer: "",
      trace: { ...apiResponse().trace, guardrail_state: "bloqueado-na-saida", rag_used: true },
    }));

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Contem dados sensiveis?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("BLOCKED_OUTPUT");
    expect(container!.textContent).not.toContain("ENTREGUE");
  });

  it("AC-RAGPII-009: deve exibir falha segura com mensagem generica", async () => {
    setupFetch(apiResponse({
      guardrail_state: "falha-segura",
      answer: "",
      trace: { retrieved_count: 0, used_count: 0, blocked_count: 0, guardrail_state: "falha-segura", total_ms: 0, sources: [], rag_used: false },
    }));

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Pergunta qualquer?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("SAFE_FAILURE");
  });

  it("AC-RAGPII-INPUT-PII: deve renderizar bloqueio-na-entrada quando input contem PII", async () => {
    setupFetch(apiResponse({
      guardrail_state: "bloqueado-na-entrada",
      answer: "Detectei dados sensiveis (PII) na sua pergunta.",
      trace: {
        retrieved_count: 0,
        used_count: 0,
        blocked_count: 0,
        guardrail_state: "bloqueado-na-entrada",
        total_ms: 0,
        sources: [],
        rag_used: false,
        input_pii_detected: true,
        input_pii_categories: ["CPF"],
        pii_categories: [],
        pii_categories_retrieval: [],
        judge_decision: "",
        judge_model: "meta/llama-3.1-8b-instruct",
        primary_model: "google/gemini-2.0-flash-001",
        fallback_used: false,
        pre_guardrail_ms: 0,
        llm_ms: 0,
        post_guardrail_ms: 0,
        pii_regex_ms: 0,
        pii_judge_ms: 0,
      },
    }));

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "meu cpf e 123.456.789-00");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("BLOCKED");
    expect(container!.textContent).toContain("BLOQUEADO NA ENTRADA");
    expect(container!.textContent).toContain("CPF");
  });

  it("AC-RAGPII-JUDGE-BLOCK: deve renderizar sentinela judge_block quando judge bloqueia sem regex", async () => {
    setupFetch(apiResponse({
      guardrail_state: "bloqueado-na-saida",
      answer: "",
      trace: {
        retrieved_count: 1,
        used_count: 1,
        blocked_count: 0,
        guardrail_state: "bloqueado-na-saida",
        total_ms: 500,
        sources: ["x.md"],
        rag_used: true,
        input_pii_detected: false,
        input_pii_categories: [],
        pii_categories: ["judge_block"],
        pii_categories_retrieval: [],
        judge_decision: "SIM",
        judge_model: "meta/llama-3.1-8b-instruct",
        primary_model: "google/gemini-2.0-flash-001",
        fallback_used: false,
        pre_guardrail_ms: 10,
        llm_ms: 200,
        post_guardrail_ms: 290,
        pii_regex_ms: 5,
        pii_judge_ms: 280,
      },
    }));

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Pergunta limpa");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("BLOCKED_OUTPUT");
    expect(container!.textContent).toContain("judge_block");
    expect(container!.textContent).toContain("SIM (bloqueou)");
  });

  it("AC-RAGPII-022: deve ter estados distinguiveis — bloqueado, entregue, safe failure", async () => {
    const states = [
      { label: "BLOCKED", data: apiResponse({ guardrail_state: "bloqueado-na-entrada", answer: "", trace: { ...apiResponse().trace, guardrail_state: "bloqueado-na-entrada", rag_used: false } }) },
      { label: "ENTREGUE", data: apiResponse() },
      { label: "SAFE_FAILURE", data: apiResponse({ guardrail_state: "falha-segura", answer: "", trace: { retrieved_count: 0, used_count: 0, blocked_count: 0, guardrail_state: "falha-segura", total_ms: 0, sources: [], rag_used: false } }) },
    ];

    for (const s of states) {
      setupFetch(s.data);
      const div = document.createElement("div");
      document.body.appendChild(div);
      await act(async () => {
        createRoot(div).render(<ChatScreen />);
      });
      const form = fillTextareaAndSubmit(div, "Q?");
      await act(async () => {
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.runAllTimersAsync();
      });
      expect(div.textContent).toContain(s.label);
      document.body.removeChild(div);
    }
  });

  it("AC-RAGPII-LIMIT: deve exibir estado LIMITE_COTA com mensagem sobre NVIDIA NIM", async () => {
    setupFetch(
      apiResponse({
        guardrail_state: "limite-cota",
        answer: "",
        trace: {
          retrieved_count: 0,
          used_count: 0,
          blocked_count: 0,
          guardrail_state: "limite-cota",
          total_ms: 0,
          sources: [],
          rag_used: false,
          rate_limit_reason: "free-models-per-day exceeded",
        },
      }),
      429,
    );

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Qual o plano?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("LIMITE_COTA");
    expect(container!.textContent).toContain("NVIDIA_NIM_API_KEY");
  });

  it("AC-RAGPII-008: deve ter SR-only announcement para acessibilidade", async () => {
    setupFetch(apiResponse());

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Pergunta teste?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    const sr = container!.querySelector(".sr-only");
    expect(sr).toBeTruthy();
    expect(sr!.textContent).toContain("entregue");
  });

  it("deve acumular mensagens em multi-turno", async () => {
    const responses = [
      apiResponse({ session_id: "ses-multi", answer: "Primeira resposta." }),
      apiResponse({ session_id: "ses-multi", answer: "Segunda resposta." }),
    ];
    let callIndex = 0;
    (globalThis as any).fetch = vi.fn().mockImplementation(() => {
      const res = responses[callIndex] || responses[responses.length - 1];
      callIndex++;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(res),
      });
    });

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form1 = fillTextareaAndSubmit(container!, "Pergunta 1?");
    await act(async () => {
      form1.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("Primeira resposta.");

    const form2 = fillTextareaAndSubmit(container!, "Pergunta 2?");
    await act(async () => {
      form2.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("Primeira resposta.");
    expect(container!.textContent).toContain("Segunda resposta.");
    expect(container!.textContent).toContain("Pergunta 1?");
    expect(container!.textContent).toContain("Pergunta 2?");
  });

  it("Enter envia mensagem (sem Shift)", async () => {
    setupFetch(apiResponse());

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    fillTextareaAndPressEnter(container!, "Teste Enter");
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("ENTREGUE");
    expect(container!.textContent).toContain("Resposta via API.");
  });

  it("Shift+Enter NAO envia mensagem", async () => {
    setupFetch(apiResponse());

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    fillTextareaAndPressShiftEnter(container!, "Teste Shift+Enter");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });

    expect(container!.textContent).not.toContain("ENTREGUE");
    expect(container!.textContent).not.toContain("Resposta via API.");
  });

  it("deve mostrar indicador RAG ACIONADO quando rag_used for true", async () => {
    setupFetch(apiResponse({ trace: { ...apiResponse().trace, rag_used: true } }));

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Q?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("ACIONADO");
  });

  it("deve mostrar indicador SEM RAG quando rag_used for false", async () => {
    setupFetch(apiResponse({ trace: { ...apiResponse().trace, rag_used: false, retrieved_count: 0, used_count: 0, blocked_count: 0, sources: [] } }));

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Oi");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("SEM RAG");
  });

  it("deve persistir sessionId em localStorage", async () => {
    setupFetch(apiResponse({ session_id: "ses-persist" }));

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Q?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(localStorage.getItem("rag-pii-chat-session-id")).toBe("ses-persist");
  });

  it("AC-RAGPII-019: deve mostrar estado partial quando historico expirar ao carregar do localStorage", async () => {
    localStorage.setItem("rag-pii-chat-session-id", "ses-old");

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: vi.fn().mockResolvedValue({ detail: "Sessao expirada" }),
    });

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(container!.querySelector("[data-testid=partial-state]")).toBeTruthy();
    expect(container!.textContent).toContain("expirou");
  });

  it("deve carregar conversa anterior do localStorage ao montar", async () => {
    localStorage.setItem("rag-pii-chat-session-id", "ses-restore");

    const historyData = conversationResponse([
      {
        question: "Olá, como funciona?",
        answer: "Funciona assim...",
        model_used: "model-test",
        guardrail_state: "entregue",
        trace: { retrieved_count: 1, used_count: 1, blocked_count: 0, guardrail_state: "entregue", total_ms: 100, sources: ["doc.md"], rag_used: true },
        timestamp: "2026-08-11T18:00:00Z",
      },
    ]);

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(historyData),
    });

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("Olá, como funciona?");
    expect(container!.textContent).toContain("Funciona assim...");
  });

  it("deve exibir botao Nova conversa apos troca de mensagens", async () => {
    setupFetch(apiResponse());

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Q?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    const newChatBtn = Array.from(container!.querySelectorAll("button:not([type=submit])"))
      .find((b) => b.textContent?.includes("Nova conversa"));
    expect(newChatBtn).toBeTruthy();
    expect(newChatBtn?.textContent).toContain("Nova conversa");
  });

  it("click em card antigo atualiza trace panel para aquela msg", async () => {
    const responses = [
      apiResponse({ session_id: "ses-click", answer: "Primeira resposta." }),
      apiResponse({ session_id: "ses-click", answer: "Segunda resposta." }),
    ];
    let callIndex = 0;
    (globalThis as any).fetch = vi.fn().mockImplementation(() => {
      const res = responses[callIndex] || responses[responses.length - 1];
      callIndex++;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(res),
      });
    });

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form1 = fillTextareaAndSubmit(container!, "Pergunta 1?");
    await act(async () => {
      form1.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    const form2 = fillTextareaAndSubmit(container!, "Pergunta 2?");
    await act(async () => {
      form2.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("Primeira resposta.");
    expect(container!.textContent).toContain("Segunda resposta.");

    const cards = container!.querySelectorAll('[data-message-id]');
    expect(cards.length).toBeGreaterThanOrEqual(3);

    const firstAssistantCard = Array.from(cards).find(
      (c) => c.getAttribute("data-message-id")?.endsWith("-a") &&
      c.textContent?.includes("Primeira resposta."),
    ) as HTMLElement | undefined;
    expect(firstAssistantCard).toBeTruthy();

    await act(async () => {
      firstAssistantCard!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container!.textContent).toContain("Primeira resposta.");
  });

  it("AC-RAGPII-TABLEEDITOR-001: botao 'Ver Tabelas de Dados' abre overlay com tabela", async () => {
    (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/admin/knowledge-documents")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            total: 2,
            limit: 20,
            offset: 0,
            table: {
              name: "knowledge_documents",
              columns: [
                { name: "id", type: "uuid", nullable: false, primary_key: true },
                { name: "source", type: "varchar(255)", nullable: false, primary_key: false },
                { name: "content", type: "text", nullable: false, primary_key: false },
                { name: "embedding", type: "vector(2048)", nullable: true, primary_key: false },
                { name: "created_at", type: "timestamptz", nullable: false, primary_key: false },
              ],
            },
            rows: [
              {
                id: "00000000-0000-0000-0000-000000000001",
                source: "planos.md",
                content: "Plano basico custa R$ 49,90 por mes.",
                embedding_summary: {
                  dim: 2048, l2_norm: 1.0, min: -0.04, max: 0.05, mean: 0.0,
                  first5: [-0.01, 0.02, -0.03, 0.04, 0.01], last5: [0.02, -0.01, 0.03, -0.02, 0.01],
                },
                created_at: "2026-08-11T18:00:00+00:00",
              },
            ],
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(apiResponse()),
      });
    });

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const openBtn = container!.querySelector('[data-testid=open-table-editor]') as HTMLButtonElement;
    expect(openBtn).toBeTruthy();
    await act(async () => {
      openBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.runAllTimersAsync();
    });

    const overlay = container!.querySelector('[role=dialog][aria-label="Table Editor"]');
    expect(overlay).toBeTruthy();
    expect(container!.textContent).toContain("Table Editor");
    expect(container!.textContent).toContain("knowledge_documents");
    expect(container!.querySelector('[data-testid=table-editor-table]')).toBeTruthy();
    expect(container!.querySelector('[data-testid=table-editor-row]')).toBeTruthy();
    expect(container!.textContent).toContain("planos.md");
    expect(container!.textContent).toContain("Plano basico custa R$ 49,90 por mes.");
    expect(container!.textContent).toContain("Voltar");
  });

  it("AC-RAGPII-TABLEEDITOR-002: botao 'Voltar' fecha o overlay e revela o chat", async () => {
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        total: 0, limit: 20, offset: 0,
        table: { name: "knowledge_documents", columns: [] },
        rows: [],
      }),
    });

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const openBtn = container!.querySelector('[data-testid=open-table-editor]') as HTMLButtonElement;
    await act(async () => {
      openBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.querySelector('[role=dialog][aria-label="Table Editor"]')).toBeTruthy();

    const backBtn = container!.querySelector('[data-testid=table-editor-back]') as HTMLButtonElement;
    expect(backBtn).toBeTruthy();
    await act(async () => {
      backBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.runAllTimersAsync();
    });

    expect(container!.querySelector('[role=dialog][aria-label="Table Editor"]')).toBeFalsy();
    expect(container!.querySelector('[data-testid=open-table-editor]')).toBeTruthy();
  });
});
