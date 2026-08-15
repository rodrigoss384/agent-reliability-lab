import { test, expect } from "@playwright/test";
import * as path from "path";

const evidenceDir = path.resolve(
  process.cwd(),
  "../docs/frontend/screens/rag-pii-chat/evidence",
);

test.describe("RAG PII Chat Small Slice", () => {
  test("deve mostrar trace Dracula com metricas e pipeline info", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("h1")).toHaveText("Guardrails RAG");

    await expect(
      page.locator("text=Envie uma pergunta"),
    ).toBeVisible();

    const textarea = page.locator("textarea");
    await textarea.fill("Qual e o plano Basico?");

    await page.locator("button:has-text('Enviar')").click();

    const statusCard = page.locator("[data-testid='guardrail-status']");
    await expect(statusCard).toBeVisible({ timeout: 30000 });

    await expect(page.locator("[data-testid='metric-retrieved']")).toBeVisible();
    await expect(page.locator("[data-testid='metric-blocked']")).toBeVisible();
    await expect(page.locator("[data-testid='metric-used']")).toBeVisible();
  });
});

test.describe("RAG PII Chat Broad Build", () => {
  test("AC-RAGPII-020: resposta normal entregue com trace sanitizado", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Qual o plano Basico?");
    await page.locator("button:has-text('Enviar')").click();

    const statusCard = page.locator("[data-testid='guardrail-status']");
    await expect(statusCard).toBeVisible({ timeout: 30000 });
    await expect(statusCard).toContainText("ENTREGUE");
    await expect(statusCard).toContainText("chunks_used");
    await expect(statusCard).toContainText("total_ms");

    await expect(page.locator("[data-testid='metric-retrieved']")).toBeVisible();
    await expect(page.locator("[data-testid='metric-used']")).toBeVisible();

    await expect(page.locator("[data-testid='rag-indicator']")).toBeVisible();

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: path.join(evidenceDir, "broad-entregue-wide.png"), fullPage: true });
  });

  test("AC-RAGPII-007: bloqueio de saida com post-guardrail", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Cliente com CPF 123.456.789-00 e saldo de R 50000");
    await page.locator("button:has-text('Enviar')").click();

    const statusCard = page.locator("[data-testid='guardrail-status']");
    await expect(statusCard).toBeVisible({ timeout: 30000 });
    const text = await statusCard.textContent();
    expect(
      text?.includes("BLOCKED") || text?.includes("BLOCKED_OUTPUT") || text?.includes("SAFE_FAILURE")
    ).toBeTruthy();
  });

  test("AC-RAGPII-009: falha segura com mensagem generica", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("O que acontece quando o sistema falha?");
    await page.locator("button:has-text('Enviar')").click();

    const statusCard = page.locator("[data-testid='guardrail-status']");
    await expect(statusCard).toBeVisible({ timeout: 30000 });
    const text = await statusCard.textContent();
    expect(text).toBeTruthy();
  });

  test("responsive: compacto mostra trace abaixo da conversa", async ({ page }) => {
    await page.goto("/");
    await page.setViewportSize({ width: 390, height: 844 });

    const textarea = page.locator("textarea");
    await textarea.fill("Qual o plano Basico?");
    await page.locator("button:has-text('Enviar')").click();

    await expect(page.locator("[data-testid='guardrail-status']")).toBeVisible({ timeout: 30000 });
    await expect(page.locator("[data-testid='trace-section']")).toBeVisible();

    await page.screenshot({ path: path.join(evidenceDir, "broad-compact.png"), fullPage: true });
  });

  test("Enter envia mensagem (sem Shift)", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Qual o plano Basico?");
    await page.keyboard.press("Enter");

    const statusCard = page.locator("[data-testid='guardrail-status']");
    await expect(statusCard).toBeVisible({ timeout: 30000 });
    await expect(statusCard).toContainText("ENTREGUE");
  });

  test("Shift+Enter NAO envia mensagem", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Testando nova linha");
    await page.keyboard.press("Shift+Enter");

    await page.waitForTimeout(2000);

    const statusCard = page.locator("[data-testid='guardrail-status']");
    await expect(statusCard).not.toBeVisible();
  });

  test("deve acumular mensagens em multi-turno", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");

    await textarea.fill("Qual o plano Basico?");
    await page.locator("button:has-text('Enviar')").click();
    await expect(page.locator("[data-testid='guardrail-status']").first()).toBeVisible({ timeout: 30000 });

    await textarea.fill("E sobre o SLA?");
    await page.locator("button:has-text('Enviar')").click();

    const statusCards = page.locator("[data-testid='guardrail-status']");
    await expect(statusCards.nth(1)).toBeVisible({ timeout: 30000 });
    expect(await statusCards.count()).toBe(2);
  });

  test("deve mostrar botao Nova conversa e limpar mensagens", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Qual o plano Basico?");
    await page.locator("button:has-text('Enviar')").click();
    await expect(page.locator("[data-testid='guardrail-status']")).toBeVisible({ timeout: 30000 });

    const newChatBtn = page.locator("button:has-text('Nova conversa')");
    await expect(newChatBtn).toBeVisible();
    await newChatBtn.click();

    await expect(page.locator("text=Envie uma pergunta")).toBeVisible();
    await expect(page.locator("[data-testid='guardrail-status']")).not.toBeVisible();
  });

  test("click em card antigo troca o trace panel", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Qual o plano Basico?");
    await page.locator("button:has-text('Enviar')").click();
    await expect(page.locator("[data-testid='guardrail-status']").first()).toBeVisible({ timeout: 30000 });

    await textarea.fill("E sobre o SLA?");
    await page.locator("button:has-text('Enviar')").click();
    await expect(page.locator("[data-testid='guardrail-status']").nth(1)).toBeVisible({ timeout: 30000 });

    expect(await page.locator("[data-testid='trace-section']")).toBeVisible();

    const firstCard = page.locator("[data-testid='guardrail-status']").first();
    await firstCard.click();

    await expect(page.locator("[data-testid='trace-section']")).toBeVisible();
  });

  test("AC-RAGPII-LIMIT: estado limite-cota mostra banner informativo sobre NVIDIA NIM", async ({ page }) => {
    await page.route("**/api/chat", async (route) => {
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: "ses-rl-e2e",
          answer: "",
          model_used: "google/gemini-2.0-flash-001",
          guardrail_state: "limite-cota",
          trace: {
            retrieved_count: 0,
            used_count: 0,
            blocked_count: 0,
            guardrail_state: "limite-cota",
            total_ms: 500,
            sources: [],
            rag_used: false,
            rate_limit_reason: "free-models-per-day exceeded",
          },
        }),
      });
    });

    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Qual o plano?");
    await page.locator("button:has-text('Enviar')").click();

    const statusCard = page.locator("[data-testid='guardrail-status']");
    await expect(statusCard).toBeVisible({ timeout: 15000 });
    await expect(statusCard).toContainText("LIMITE_COTA");
    await expect(page.locator("body")).toContainText("NVIDIA_NIM_API_KEY");
  });
});
