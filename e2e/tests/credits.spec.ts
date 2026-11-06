/**
 * The credits endpoints through the app's own address (credits plan phases 10.2 and 10.3). The credit gate and earning are
 * not switched on in the stack yet (the open gate and the do-nothing sink are the defaults until phase 10.9), so nothing a
 * learner does costs or earns anything; what is live is the signup grant, the wallet, the quote, the history and the streak,
 * and they must answer correctly through the Next.js proxy.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";

test("a new learner has the 30 signup credits, and the wallet, the quote and the history answer for them", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("credits"), E2E.PASSWORD);

  const wallet = await api.call("GET", "/credits/wallet");
  expect(wallet.status).toBe(200);
  expect(wallet.body).toEqual({
    balance: 30,
    held: 0,
    buckets: [{ source: "signup", remaining: 30, expires_at: null }],
    next_expiry: null,
    exempt: false,
  });

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
  expect(history.body.results.map((row: { text: string }) => row.text)).toEqual(["Welcome gift: 30 credits"]);
});

test("the plans on offer carry the spec's prices in paise, and a new learner has none running", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("plans"), E2E.PASSWORD);

  const plans = await api.call("GET", "/credits/plans");

  expect(plans.status).toBe(200);
  const byKey = Object.fromEntries(plans.body.plans.map((plan: { key: string }) => [plan.key, plan]));
  expect(Object.keys(byKey)).toEqual(["one_time", "weekly_pro", "monthly_pro", "pro_plus"]);
  expect(byKey.weekly_pro).toMatchObject({ credits: 100, period_days: 7, price_paise: 4900, max_quantity: 12 });
  expect(byKey.monthly_pro).toMatchObject({ credits: 500, period_days: 28, price_paise: 19900 });
  expect(byKey.pro_plus).toMatchObject({ credits: 750, period_days: 28, price_paise: 27900 });
  expect(plans.body.one_time).toEqual({ min_credits: 10, max_credits: 5000, price_paise_per_credit: 100, valid_days: 365 });
  expect(plans.body.periods).toEqual([]);
  expect(plans.body.queue).toEqual({ open: 0, limit: 12 });
});

test("a new learner has no streak, nothing to repair, and the read changes nothing", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("streak"), E2E.PASSWORD);

  const streak = await api.call("GET", "/credits/streak");

  expect(streak.status).toBe(200);
  expect(streak.body).toMatchObject({ current: 0, longest: 0, alive: false, zone: "Asia/Kolkata" });
  expect(streak.body.today.done).toBe(false);
  expect(streak.body.days).toHaveLength(28);
  expect(streak.body.next_bonus).toEqual({ streak_day: 7, credits: 10, days_to_go: 7 });
  expect(streak.body.repair).toMatchObject({ available: false, reason: "nothing_to_repair", cost: 1 });
  expect((await api.call("GET", "/credits/wallet")).body.balance).toBe(30);

  const repair = await api.call("POST", "/credits/streak/repair");
  expect(repair.status).toBe(409);
  expect(repair.body.code).toBe("nothing_to_repair");
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
  expect((await stranger.get("/api/credits/streak")).status()).toBe(401);
  expect((await stranger.get("/api/credits/plans")).status()).toBe(401);
  await stranger.dispose();
});
