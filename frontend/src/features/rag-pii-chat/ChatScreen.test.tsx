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
});

describe("RAG PII Chat Broad Build", () => {
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
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
      answer: "Desculpe, a resposta gerada foi bloqueada por conter dados sensiveis.",
      trace: { ...apiResponse().trace, guardrail_state: "bloqueado-na-saida" },
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
      answer: "Desculpe, ocorreu uma falha na verificacao da resposta.",
      trace: { retrieved_count: 0, used_count: 0, blocked_count: 0, guardrail_state: "falha-segura", total_ms: 0, sources: [] },
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

  it("AC-RAGPII-022: deve ter estados distinguiveis — bloqueado, entregue, safe failure", async () => {
    const states = [
      { label: "BLOCKED", data: apiResponse({ guardrail_state: "bloqueado-na-entrada", answer: "", trace: { ...apiResponse().trace, guardrail_state: "bloqueado-na-entrada" } }) },
      { label: "ENTREGUE", data: apiResponse() },
      { label: "SAFE_FAILURE", data: apiResponse({ guardrail_state: "falha-segura", answer: "", trace: { retrieved_count: 0, used_count: 0, blocked_count: 0, guardrail_state: "falha-segura", total_ms: 0, sources: [] } }) },
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

  it("AC-RAGPII-019: deve mostrar estado partial quando API retornar 404 no historico", async () => {
    setupFetch(apiResponse());

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Q1?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: vi.fn().mockResolvedValue({ detail: "Sessao expirada" }),
    });

    const historyBtn = container!.querySelector("[data-testid=load-history-btn]") as HTMLButtonElement;
    expect(historyBtn).toBeTruthy();
    await act(async () => {
      historyBtn.click();
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("Sessão expirou");
    expect(container!.querySelector("[data-testid=partial-state]")).toBeTruthy();
  });

  it("AC-RAGPII-016: deve exibir historico sanitizado com apenas turns entregues", async () => {
    setupFetch(apiResponse());

    await act(async () => {
      const root = createRoot(container!);
      root.render(<ChatScreen />);
    });

    const form = fillTextareaAndSubmit(container!, "Q1?");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await vi.runAllTimersAsync();
    });

    const historyData = conversationResponse([
      {
        question: "Q1?",
        answer: "Resposta via API.",
        model_used: "google/gemini-2.0-flash-001",
        guardrail_state: "entregue",
        trace: { retrieved_count: 2, used_count: 1, blocked_count: 1, guardrail_state: "entregue", total_ms: 100, sources: ["planos.md"] },
        timestamp: "2026-08-11T18:00:00Z",
      },
    ]);

    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(historyData),
    });

    const historyBtn = container!.querySelector("[data-testid=load-history-btn]") as HTMLButtonElement;
    await act(async () => {
      historyBtn.click();
      await vi.runAllTimersAsync();
    });

    expect(container!.textContent).toContain("Histórico da sessão");
    expect(container!.textContent).toContain("Q1?");
    expect(container!.textContent).toContain("Resposta via API.");
  });
});
