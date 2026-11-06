/**
 * The credits endpoints and screens through the app's own address (credits plan phases 10.2, 10.3 and 10.5). The stack
 * charges and earns for real (docker-compose.e2e.yml: the credit gate and the credits sink; the dev default stays the open
 * gate until phase 10.9), so what is checked here is live: the signup grant, the wallet, the quote, the history, the streak
 * and the plans answering correctly through the Next.js proxy, and the screens built on them (the cost beside a button, the
 * wallet and its history, the streak, the notices, and what a learner who cannot pay is told). Credits are seeded with
 * `support/seed.ts`; the daily credit is large on this stack (see `make fake-llm`), so the history, not the balance, is the
 * witness for what was reserved.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";
import { Seed } from "../support/seed";

test("a new learner has the 30 signup credits, and the wallet, the quote and the history answer for them", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("credits"), E2E.PASSWORD);

  const wallet = await api.call("GET", "/credits/wallet");
  expect(wallet.status).toBe(200);
  expect(wallet.body).toEqual({
    balance: 30,
    reserved: 0,
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

// --- The credit screens, with the gate and earning switched on (credits plan phase 10.5) ----------------------------------

test("the cost shown on the new-lesson form is what is reserved for the lesson", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("cost"), E2E.PASSWORD);

  await page.goto("/lessons/new");
  await page.getByLabel("Topic").fill("Photosynthesis");
  const label = page.getByTestId("cost-label");
  await expect(label).toBeVisible();
  await expect(label).toContainText("3 credits now, 7 after the Quick check");
  await expect(label).toContainText("10 credits in all");
  const shown = Number(await label.getAttribute("data-credits"));
  expect(shown).toBe(3);

  // Choosing study sheets changes the price on the same form: the number follows the choice.
  await page.getByText("Study sheets", { exact: true }).click();
  await expect(page.getByTestId("cost-label")).toContainText("5 credits in all");
  await page.getByText("A lesson", { exact: true }).click();
  await expect(page.getByTestId("cost-label")).toContainText("10 credits in all");

  await page.getByRole("button", { name: /start my quick check/i }).click();
  await page.waitForURL(/\/lessons\/[0-9a-f-]{36}/, { waitUntil: "commit" });

  // What was set aside is read from the history, not the balance: the first study of the day earns a credit as well, and
  // it would move the balance.
  const lessonId = /\/lessons\/([0-9a-f-]{36})/.exec(page.url())![1]!;
  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
  const rows = (await api.call("GET", "/credits/transactions")).body.results as { kind: string; amount: number }[];
  const reserved = rows.filter((row) => row.kind === "reserved");
  expect(reserved).toHaveLength(1);
  expect(Math.abs(reserved[0]!.amount)).toBe(shown);
});

test("the wallet, the history and the header chip say what the API says", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("wallet"), E2E.PASSWORD);
  const lessonId = (await api.call("POST", "/lessons", { topic: "Binary search", entry: "self_rating", self_rating: 4 })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "ready");

  // The day's credit is written as the run is settled, a moment after the lesson is ready: wait for it, so the API and the
  // screen are read at the same balance.
  await expect
    .poll(async () => ((await api.call("GET", "/credits/transactions")).body.results as { text: string }[]).some((row) => /studying today/i.test(row.text)))
    .toBe(true);
  const wallet = (await api.call("GET", "/credits/wallet")).body;
  await page.goto("/wallet");
  const balance = page.getByTestId("wallet-balance");
  await expect(balance).toHaveAttribute("data-balance", String(wallet.balance));
  await expect(page.getByTestId("balance-chip")).toContainText(String(wallet.balance));
  expect(await page.getByTestId("wallet-groups").locator("li").count()).toBe(
    new Set(wallet.buckets.map((b: { source: string; expires_at: string | null }) => `${b.source}|${b.expires_at?.slice(0, 10)}`)).size,
  );

  // The history is the API's rows in the API's order, in the same words.
  const history = (await api.call("GET", "/credits/transactions")).body.results as { text: string }[];
  await page.goto("/wallet/history");
  const rows = page.getByTestId("history-row");
  await expect(rows).toHaveCount(history.length);
  for (const [n, row] of history.entries()) await expect(rows.nth(n)).toContainText(row.text);
  await expect(page.getByText(/ledger|bucket|hold/i)).toHaveCount(0); // none of the machinery reaches a learner
});

test("the streak screen shows today's study, and the daily credit has come in", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("streak-screen"), E2E.PASSWORD);

  await page.goto("/streak");
  await expect(page.getByTestId("streak-headline")).toHaveText(/No streak yet/);
  await expect(page.getByTestId("streak-today")).toHaveAttribute("data-done", "false");
  await expect(page.getByTestId("repair-reason")).toBeVisible(); // nothing to repair, and it says so
  await expect(page.getByTestId("streak-days").locator("li")).toHaveCount(28);

  const lessonId = (await api.call("POST", "/lessons", { topic: "Binary search", entry: "self_rating", self_rating: 4 })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "ready");
  await expect.poll(async () => (await api.call("GET", "/credits/streak")).body.today.done).toBe(true); // recorded as the run is settled

  await page.goto("/streak");
  await expect(page.getByTestId("streak-headline")).toHaveText(/1-day streak/);
  await expect(page.getByTestId("streak-today")).toHaveAttribute("data-done", "true");
  const today = (await api.call("GET", "/credits/streak")).body.today.date as string;
  await expect(page.getByTestId("streak-days").locator(`li[data-date="${today}"]`)).toHaveAttribute("data-state", "active");
  const rows = (await api.call("GET", "/credits/transactions")).body.results as { text: string }[];
  expect(rows.some((row) => /studying today/i.test(row.text))).toBe(true);
});

test("a learner with too few credits for the rest of a lesson keeps their answers, is shown how to get more, and carries on", async ({ page }) => {
  const api = new Api(page);
  const email = E2E.email("poor");
  await api.signUp(email, E2E.PASSWORD);
  Seed.leave(email, 3); // enough for the Quick check, not for the lesson after it

  const lessonId = (await api.call("POST", "/lessons", { topic: "Photosynthesis" })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
  // The Quick check being made is the first study of the day, which earns the day's credit (a large one on this stack):
  // wait for it, then leave the learner with nothing, so the rest of the lesson is what they cannot pay for.
  await expect
    .poll(async () => ((await api.call("GET", "/credits/transactions")).body.results as { text: string }[]).some((row) => /studying today/i.test(row.text)))
    .toBe(true);
  Seed.leave(email, 0);
  await page.goto(`/lessons/${lessonId}`);
  await new Deck(page).answerAll(Deck.rightOrDontKnow);

  const card = page.getByTestId("quick-check-needs-credits");
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card).toContainText("You need 7 credits");
  await expect(card).toContainText("Your answers are saved on this page");
  await expect(page.getByRole("link", { name: "Get more credits" })).toHaveAttribute("href", "/buy");

  // Buying is not open yet, so the credits come from a gift; the answers are still there to send.
  Seed.give(email, 20);
  await page.getByRole("button", { name: "Send my answers" }).click();
  await api.until(lessonId, (lesson) => lesson.stage === "ready");
});

test("a learner who cannot pay is told so beside the button, and the refusal offers the way to buy", async ({ page }) => {
  const api = new Api(page);
  const email = E2E.email("short");
  await api.signUp(email, E2E.PASSWORD);
  Seed.leave(email, 2);

  await page.goto("/lessons/new");
  await page.getByLabel("Topic").fill("Photosynthesis");
  await expect(page.getByTestId("cost-label")).toContainText("You have 2 credits; this needs 3 credits.");
  await expect(page.getByTestId("cost-label").getByRole("link", { name: "Buy credits" })).toHaveAttribute("href", "/buy");

  await page.getByRole("button", { name: /start my quick check/i }).click(); // still pressable: the server decides
  await expect(page.getByRole("alert").filter({ hasText: /you need 3 credits/i })).toBeVisible();
  await expect(page.getByText("Not enough credits").first()).toBeVisible();
  await page.getByRole("button", { name: "Buy credits" }).click();
  await page.waitForURL(/\/buy$/);
  await expect(page.getByTestId("buy-one_time")).toBeVisible(); // the fake gateway is on in this stack, so buying is open
  expect((await api.call("GET", "/lessons")).body.results).toHaveLength(0); // nothing was made
});

test("credits about to run out are told in a banner that can be put away for the day, and on the wallet", async ({ page }) => {
  const api = new Api(page);
  const email = E2E.email("notice");
  await api.signUp(email, E2E.PASSWORD);
  Seed.grantExpiring(email, 40, 2);

  const notices = (await api.call("GET", "/credits/notices")).body.notices as { text: string; credits: number; days_left: number }[];
  expect(notices).toHaveLength(1);
  expect(notices[0]).toMatchObject({ credits: 40, days_left: 2 });
  expect((await api.call("GET", "/credits/balance")).body.notices).toBe(1);

  await page.goto("/lessons");
  const banner = page.getByTestId("notices-banner");
  await expect(banner).toBeVisible();
  await expect(banner.getByTestId("notice-text")).toContainText(notices[0]!.text);

  await page.goto("/wallet");
  await expect(page.getByTestId("wallet-notices")).toContainText(notices[0]!.text);
  await expect(page.getByTestId("wallet-groups")).toContainText("Daily credits");

  await page.getByRole("button", { name: "Hide this for today" }).click();
  await expect(banner).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("notices-banner")).toHaveCount(0); // still put away after a reload
  await expect(page.getByTestId("wallet-notices")).toContainText(notices[0]!.text); // the wallet always says
});

test("the credit screens hold at the width of a phone", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("phone"), E2E.PASSWORD);
  await page.setViewportSize({ width: 400, height: 800 });

  for (const path of ["/wallet", "/wallet/history", "/streak", "/buy", "/lessons/new"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${path} scrolls sideways`).toBeLessThanOrEqual(0);
  }
});
