/**
 * Signing up with a code (phase 11.1). A person who creates an account is sent a six-digit code and has no account until
 * they enter it in the browser that asked; only then are there credits. The code comes from the throwaway stack's outbox, the
 * way a learner would read it in their inbox. An account from before verification existed keeps its sign-in with no code
 * until `require_reverification` is run (the launch step), and then it is asked for one.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Outbox } from "../support/outbox";
import { Seed } from "../support/seed";

async function register(page: import("@playwright/test").Page, email: string): Promise<void> {
  await page.goto("/auth?mode=register");
  await page.getByLabel("Name").fill("Sign In Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(E2E.PASSWORD);
  await page.locator("input[name=accept_terms]").check();
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/auth\/verify/);
}

test("creating an account asks for the emailed code, refuses a wrong one, and gives 30 credits only after the right one", async ({ page }) => {
  const email = E2E.email("code");
  await register(page, email);
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();

  const api = new Api(page);
  expect((await api.call("GET", "/auth/me")).status).toBe(401); // no account, no session, yet

  const code = await Outbox.code(page.request, email);
  const wrong = code === "000000" ? "111111" : "000000";
  await page.getByLabel("6-digit code").fill(wrong);
  await expect(page.getByText("That code didn't work. Check it, or ask for a new one.")).toBeVisible();
  expect((await api.call("GET", "/auth/me")).status).toBe(401);

  await page.getByLabel("6-digit code").fill(code.slice(0, 3) + " " + code.slice(3)); // pasted the way the email shows it
  await page.waitForURL(/\/onboarding/);

  const wallet = await api.call("GET", "/credits/wallet");
  expect(wallet.body).toMatchObject({ balance: 30, buckets: [{ source: "signup", remaining: 30 }] });
});

test("a new code can be asked for after the wait, and the old one stops working", async ({ page }) => {
  const email = E2E.email("resend");
  await page.clock.install();
  await register(page, email);
  const first = await Outbox.code(page.request, email);

  const button = page.getByRole("button", { name: /Send a new code/ });
  await expect(button).toBeDisabled(); // a minute's wait, so nobody is invited to press what would be refused
  await page.clock.fastForward(61_000);
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.getByText("We sent a new code. The old one no longer works.")).toBeVisible();

  const second = await Outbox.code(page.request, email, "signup_code", 1);
  expect(second).toMatch(/^\d{6}$/);
  if (first !== second) {
    const stale = await new Api(page).call("POST", "/auth/verify", { email, code: first, purpose: "signup" });
    expect(stale.status).toBe(400);
  }
  await page.getByLabel("6-digit code").fill(second);
  await page.waitForURL(/\/onboarding/);
});

test("a visitor who lost their browser's ticket is offered to start again", async ({ page }) => {
  await page.goto("/auth/verify");

  await expect(page.getByText("We've lost track of where we sent your code.")).toBeVisible();
  await page.getByRole("button", { name: "Start again" }).click();
  await expect(page).toHaveURL(/\/auth\?mode=register/);
});

test("an account from before verification signs in with no code, and is asked for one once reverification is required", async ({ page }) => {
  const kept = E2E.email("legacy-kept");
  Seed.legacyAccount(kept, E2E.PASSWORD, { reverify: false });
  await page.goto("/auth");
  await page.getByLabel("Email").fill(kept);
  await page.getByLabel("Password", { exact: true }).fill(E2E.PASSWORD);
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/onboarding/); // signed in with no code

  const asked = E2E.email("legacy-asked");
  Seed.legacyAccount(asked, E2E.PASSWORD, { reverify: true });
  await page.context().clearCookies();
  await page.goto("/auth");
  await page.getByLabel("Email").fill(asked);
  await page.getByLabel("Password", { exact: true }).fill(E2E.PASSWORD);
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/auth\/verify\?purpose=login/);

  await page.getByLabel("6-digit code").fill(await Outbox.code(page.request, asked, "login_code"));
  await page.waitForURL(/\/onboarding/);
});
