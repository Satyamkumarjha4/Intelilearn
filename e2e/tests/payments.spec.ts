/**
 * Buying credits in a browser against the fake payment gateway (credits plan phase 10.6). The stack enables only the fake
 * gateway; the test plays the provider by sending a signed callback to the webhook through the frontend's own address.
 *
 * Why: the unit tests prove each rule, but only a browser shows the seams: that the proxy keeps the raw body and the
 * signature header so a callback verifies, that the page a learner comes back to waits for the server and grants nothing
 * itself, that a forged or mismatched callback changes nothing, and that someone too poor for the rest of a lesson can buy,
 * come back and send their saved answers.
 *
 * Use cases:
 * - one-time credits: pick an amount, pay (the fake provider's page is the return page), and the balance rises only after a
 *   signed callback; the same callback again changes nothing; the history says so
 * - a plan by the week: the first week's credits arrive at once and the rest are lined up
 * - the return page alone grants nothing, however its address is dressed up; a callback with a wrong signature or the wrong
 *   amount is refused or ignored and grants nothing
 * - with one way to pay there is no picker
 * - a learner too poor for the rest of a lesson buys, comes back to the lesson, and sends the answers that were kept
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";
import { Provider } from "../support/provider";
import { Seed } from "../support/seed";

async function balance(api: Api): Promise<number> {
  return (await api.call("GET", "/credits/wallet")).body.balance;
}

test("one-time credits arrive only after the provider's signed callback", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("buy"), E2E.PASSWORD);
  const provider = new Provider(page);
  const eventId = `evt-buy-${Date.now()}`; // an event id is used once for ever, so a rerun on the same stack needs a new one

  await page.goto("/buy");
  await expect(page.getByText("How would you like to pay?")).toHaveCount(0); // one way to pay: nothing to choose
  await page.getByTestId("chip-200").click();
  await expect(page.getByTestId("amount-help")).toHaveText("₹200 for 200 credits");
  await page.getByTestId("buy-one_time").click();
  await page.waitForURL(/\/buy\/return\?order=/);

  const orderId = new URL(page.url()).searchParams.get("order")!;
  const order = (await api.call("GET", `/payments/orders/${orderId}`)).body;
  expect(order).toMatchObject({ status: "pending", amount_paise: 20000, credits: 200 });
  await expect(page.getByTestId("return-headline")).toHaveText("Confirming your payment");
  expect(await balance(api)).toBe(30); // nothing yet: coming back from paying grants nothing

  expect((await provider.say("succeeded", order, { eventId })).status).toBe(200);

  await expect(page.getByTestId("return-headline")).toHaveText("Your credits are here", { timeout: 30_000 });
  await expect(page.getByTestId("return-balance")).toHaveAttribute("data-balance", "230");
  expect(await balance(api)).toBe(230);
  expect((await api.call("GET", `/payments/orders/${orderId}`)).body.status).toBe("fulfilled");

  expect((await provider.say("succeeded", order, { eventId })).status).toBe(200); // the provider retries
  expect(await balance(api)).toBe(230);

  const history = (await api.call("GET", "/credits/transactions")).body.results as { text: string }[];
  expect(history.map((row) => row.text)).toContain("Bought 200 credits");
  await page.getByTestId("return-carry-on").click();
  await page.waitForURL(/\/lessons/);
});

test("a plan by the week gives its first week at once and lines up the rest", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("buy-plan"), E2E.PASSWORD);

  await page.goto("/buy");
  await page.getByRole("button", { name: "One week more" }).click();
  await expect(page.getByTestId("plan-weekly_pro-weeks")).toHaveText("2 weeks");
  await expect(page.getByTestId("buy-weekly_pro")).toContainText("₹98");
  await page.getByTestId("buy-weekly_pro").click();
  await page.waitForURL(/\/buy\/return\?order=/);

  const order = (await api.call("GET", `/payments/orders/${new URL(page.url()).searchParams.get("order")}`)).body;
  expect(order).toMatchObject({ amount_paise: 9800, quantity: 2, credits: 200 });
  await new Provider(page).say("succeeded", order);

  await expect(page.getByTestId("return-headline")).toHaveText("Your credits are here", { timeout: 30_000 });
  expect(await balance(api)).toBe(130); // 30 + the first week's 100
  await page.goto("/buy");
  await expect(page.getByTestId("buy-periods").locator("li")).toHaveCount(2);
  await expect(page.getByTestId("buy-periods")).toContainText("Running");
  await expect(page.getByTestId("buy-periods")).toContainText("Waiting");
});

test("the return page alone, a wrong signature and a wrong amount grant nothing", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("buy-forged"), E2E.PASSWORD);
  const provider = new Provider(page);
  const created = await api.call("POST", "/payments/orders", { plan: "one_time", credits: 100 });
  const order = created.body;

  await page.goto(`/buy/return?order=${order.id}&paid=true&status=fulfilled&session_id=cs_forged`);
  await expect(page.getByTestId("return-headline")).toHaveText("Confirming your payment");
  expect(await balance(api)).toBe(30);

  const forged = await provider.say("succeeded", order, { secret: "not-the-secret" });
  expect(forged.status).toBe(400);
  const wrongAmount = await provider.say("succeeded", order, { amount: 1 });
  expect(wrongAmount.status).toBe(200); // answered, so the provider does not retry; recorded, and nothing is granted
  expect(await balance(api)).toBe(30);
  expect((await api.call("GET", `/payments/orders/${order.id}`)).body.status).toBe("pending");

  expect((await provider.say("succeeded", order)).status).toBe(200);
  expect(await balance(api)).toBe(130);
});

test("a refund takes back only what is unspent", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("buy-refund"), E2E.PASSWORD);
  const order = (await api.call("POST", "/payments/orders", { plan: "one_time", credits: 100 })).body;
  const provider = new Provider(page);
  await provider.say("succeeded", order);
  expect(await balance(api)).toBe(130);

  await provider.say("refunded", order, { amount: 5000 }); // half: 50 credits

  expect(await balance(api)).toBe(80);
  expect((await api.call("GET", `/payments/orders/${order.id}`)).body.refunded_paise).toBe(5000);
});

test("a learner too poor for the rest of a lesson buys, comes back, and sends the answers that were kept", async ({ page }) => {
  const api = new Api(page);
  const email = E2E.email("buy-poor");
  await api.signUp(email, E2E.PASSWORD);
  const provider = new Provider(page);

  const lessonId = (await api.call("POST", "/lessons", { topic: "Photosynthesis" })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
  await expect
    .poll(async () => ((await api.call("GET", "/credits/transactions")).body.results as { text: string }[]).some((row) => /studying today/i.test(row.text)))
    .toBe(true);
  Seed.leave(email, 0);

  await page.goto(`/lessons/${lessonId}`);
  await new Deck(page).answerAll(Deck.rightOrDontKnow);
  await expect(page.getByTestId("quick-check-needs-credits")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("link", { name: "Get more credits" }).click();
  await page.waitForURL(/\/buy$/);
  await page.getByTestId("chip-50").click();
  await page.getByTestId("buy-one_time").click();
  await page.waitForURL(/\/buy\/return\?order=/);
  const order = (await api.call("GET", `/payments/orders/${new URL(page.url()).searchParams.get("order")}`)).body;
  await provider.say("succeeded", order);
  await expect(page.getByTestId("return-headline")).toHaveText("Your credits are here", { timeout: 30_000 });

  await page.getByTestId("return-carry-on").click(); // back where they were: the lesson
  await page.waitForURL(new RegExp(`/lessons/${lessonId}`));
  await expect(page.getByTestId("quick-check-resume")).toBeVisible();
  expect(await api.stage(lessonId)).toBe("awaiting_diagnostic"); // nothing was sent for them: a charge follows a click
  await page.getByRole("button", { name: "Send my answers" }).click();
  await api.until(lessonId, (lesson) => lesson.stage === "ready");
});
