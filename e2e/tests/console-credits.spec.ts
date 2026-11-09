/**
 * The staff console's money screens in a browser (credits plan phase 10.9): prices, a learner's wallet, payments and the
 * revenue block, on the stack where credits are on.
 *
 * Why: the unit and API tests prove each rule, but only a browser shows that the screens fit them: that a price edited in
 * the page is the one the API then holds (with its old value kept as history), that the give-or-take form will not move
 * credits without a reason, that a learner's balance changes where the learner sees it, and that the screens a stranger
 * must not reach stay a 404.
 *
 * Use cases:
 * - staff change a price on /console/credits and save it: the API's live price is the new one and the history has the old
 *   one; the price is put back at the end so the other specs' costs are unchanged
 * - staff open a learner's wallet from the learner's address: giving credits without a reason is refused in the page and
 *   moves nothing; with a reason it adds them, and the learner's own wallet shows the new balance
 * - staff delete a learner's data from the learner's page: the button waits for the account's email to be typed, the
 *   learner's sign-in stops working, and the page then says the account is erased
 * - /console/payments opens with its three tiles and /console/usage shows revenue beside model cost with the dollar rate
 * - a learner who opens the credit console pages, or the wallet endpoint, gets the page that does not exist
 */
import { expect, test, type Page } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";

async function staffPage(browser: import("@playwright/test").Browser): Promise<{ page: Page; api: Api }> {
  const page = await (await browser.newContext()).newPage();
  const api = new Api(page);
  expect((await api.call("POST", "/auth/login", { email: E2E.STAFF_EMAIL, password: E2E.STAFF_PASSWORD })).status).toBe(200);
  return { page, api };
}

test("a price edited in the console is the live price, and the old one is kept", async ({ browser }) => {
  const { page, api } = await staffPage(browser);
  const live = async () => (await api.call("GET", "/console/credits")).body.prices.find((price: { key: string }) => price.key === "lesson.check");
  const before = await live();
  try {
    await page.goto("/console/credits");
    const box = page.getByLabel("Credits for lesson.check", { exact: true });
    await expect(box).toHaveValue(String(before.credits));
    await box.fill(String(before.credits + 1));
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText(/Saved\. The next reserve/)).toBeVisible();

    const after = await live();
    expect(after.credits).toBe(before.credits + 1);
    expect(after.history.map((row: { credits: number }) => row.credits).slice(0, 2)).toEqual([before.credits + 1, before.credits]);
  } finally {
    await api.call("PATCH", "/console/credits/prices/lesson.check", { credits: before.credits });
  }
  expect((await live()).credits).toBe(before.credits);
});

test("a wallet change needs a reason, and the learner sees the new balance", async ({ browser }) => {
  const learner = await (await browser.newContext()).newPage();
  const learnerApi = new Api(learner);
  await learnerApi.signUp(E2E.email("wallet"), E2E.PASSWORD);
  const me = (await learnerApi.call("GET", "/auth/me")).body;
  const start = (await learnerApi.call("GET", "/credits/wallet")).body.balance;

  const { page } = await staffPage(browser);
  await page.goto(`/console/learners/${me.id}`);
  await expect(page.getByText("Can spend now")).toBeVisible();

  await page.getByLabel("Credits", { exact: true }).fill("5");
  await page.getByRole("button", { name: "Give 5 credits" }).click();
  await expect(page.getByText("Say why the credits are being given or taken.")).toBeVisible();
  expect((await learnerApi.call("GET", "/credits/wallet")).body.balance).toBe(start);

  await page.getByLabel("Reason (required)").fill("Goodwill after a slow lesson");
  await page.getByRole("button", { name: "Give 5 credits" }).click();
  await expect(page.getByText(/The movement is on the ledger/)).toBeVisible();
  await expect.poll(async () => (await learnerApi.call("GET", "/credits/wallet")).body.balance).toBe(start + 5);
  await expect(page.getByRole("table", { name: /ledger rows/i }).getByText("Goodwill after a slow lesson")).toBeVisible();
});

test("payments opens, and usage shows revenue beside model cost with its rate", async ({ browser }) => {
  const { page } = await staffPage(browser);

  await page.goto("/console/payments");
  await expect(page.getByRole("heading", { name: "Payments" }).first()).toBeVisible();
  await expect(page.getByText("Refunds waiting")).toBeVisible();

  await page.goto("/console/usage?range=30d");
  await expect(page.getByRole("heading", { name: "Revenue and model cost" })).toBeVisible();
  await expect(page.getByText(/to the dollar/)).toBeVisible();
});

test("a learner meets the page that does not exist, and the endpoints answer 404", async ({ browser }) => {
  const learner = await (await browser.newContext()).newPage();
  const api = new Api(learner);
  await api.signUp(E2E.email("not-staff"), E2E.PASSWORD);

  for (const path of ["/console/credits", "/console/payments"]) {
    await learner.goto(path);
    await expect(learner.getByText(/couldn.t find that page/i)).toBeVisible();
  }
  for (const path of ["/console/credits", "/console/payments", "/console/revenue"]) {
    expect((await api.call("GET", path)).status).toBe(404);
  }
});

test("deleting a learner needs their email, ends their sign-in, and the page then says so", async ({ browser }) => {
  const learner = await (await browser.newContext()).newPage();
  const learnerApi = new Api(learner);
  const email = E2E.email("erase-me");
  await learnerApi.signUp(email, E2E.PASSWORD);
  const me = (await learnerApi.call("GET", "/auth/me")).body;
  expect((await learnerApi.call("GET", "/auth/me")).status).toBe(200);

  const { page } = await staffPage(browser);
  await page.goto(`/console/learners/${me.id}`);
  const button = page.getByRole("button", { name: "Delete this learner's data" });
  await expect(button).toBeDisabled();
  await page.getByLabel("Type the account's email to confirm").fill("someone-else@example.com");
  await expect(button).toBeDisabled();

  await page.getByLabel("Type the account's email to confirm").fill(email.toUpperCase());
  await expect(button).toBeEnabled();
  await button.click();

  await expect(page.getByText(/^Erased: /)).toBeVisible();
  await expect(page.getByText(/already been erased/)).toBeVisible();
  expect((await learnerApi.call("GET", "/auth/me")).status).toBe(401);
});
