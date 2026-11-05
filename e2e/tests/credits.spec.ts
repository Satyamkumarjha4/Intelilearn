/**
 * The credits endpoints through the app's own address (credits plan phase 10.2). The credit gate is not switched on in the
 * stack yet (the open gate is the default until phase 10.9), so nothing a learner does costs anything; what is live is the
 * wallet, the quote and the history, and they must answer correctly through the Next.js proxy.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";

test("the wallet, the quote and the history answer for a learner, and the quote knows the plan's prices", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("credits"), E2E.PASSWORD);

  const wallet = await api.call("GET", "/credits/wallet");
  expect(wallet.status).toBe(200);
  expect(wallet.body).toEqual({ balance: 0, held: 0, buckets: [], next_expiry: null, exempt: false });

  const check = await api.call("POST", "/credits/quote", {
    action: "lesson.create",
    size: { entry: "diagnostic", intent: "lesson", origin: "direct", covers: "diagnostic" },
  });
  expect(check.status).toBe(200);
  expect(check.body).toMatchObject({ due_now: 3, later: 7, total: 10, exempt: false });
  expect(check.body.lines[0]).toMatchObject({ key: "lesson.check", credits: 3 });

  const sheets = await api.call("POST", "/credits/quote", {
    action: "lesson.create",
    size: { entry: "diagnostic", intent: "sheets", origin: "direct", covers: "diagnostic", sheets: 2, grounding: "quiz" },
  });
  expect(sheets.body).toMatchObject({ due_now: 3, later: 2, total: 5 });

  const history = await api.call("GET", "/credits/transactions");
  expect(history.status).toBe(200);
  expect(history.body.results).toEqual([]);
});

test("the quote refuses what is not a real question, and nobody signed out can ask", async ({ page, playwright, baseURL }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("credits-refused"), E2E.PASSWORD);

  const unknownHint = await api.call("POST", "/credits/quote", { action: "lesson.create", size: { entry: "diagnostic", free: true } });
  expect(unknownHint.status).toBe(400);
  expect(unknownHint.body.fields).toHaveProperty("size");

  const unknownAction = await api.call("POST", "/credits/quote", { action: "lesson.invented", size: {} });
  expect(unknownAction.status).toBe(400);
  expect(unknownAction.body.fields).toHaveProperty("action");

  const stranger = await playwright.request.newContext({ baseURL });
  expect((await stranger.get("/api/credits/wallet")).status()).toBe(401);
  expect((await stranger.get("/api/credits/transactions")).status()).toBe(401);
  await stranger.dispose();
});
