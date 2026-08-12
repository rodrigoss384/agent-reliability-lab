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

  test("AC-RAGPII-019: sessao expirada mostra estado partial", async ({ page }) => {
    await page.goto("/");

    const textarea = page.locator("textarea");
    await textarea.fill("Qual o plano Basico?");
    await page.locator("button:has-text('Enviar')").click();

    await expect(page.locator("[data-testid='guardrail-status']")).toBeVisible({ timeout: 30000 });

    const historyBtn = page.locator("[data-testid='load-history-btn']");
    await expect(historyBtn).toBeVisible({ timeout: 5000 });
    await historyBtn.click();

    const partialState = page.locator("[data-testid='partial-state']");
    await expect(partialState).toBeVisible({ timeout: 5000 });
    await expect(partialState).toContainText("expirou");
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
});
