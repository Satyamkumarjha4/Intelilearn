/**
 * The staff console's sign-in screens in a browser (phase 11.4): the people waiting for a code, a learner's verification
 * panel, and the abuse board with its switch.
 *
 * Why: the unit and API tests prove each rule (an action needs a reason, an approval leaves no password, a stranger gets a
 * 404, the numbers are the events), but only a browser shows that a person who registered and never entered their code
 * really appears for staff, that the page will not approve them without a reason, that what it makes is an account nobody
 * can sign in to with the password typed at sign-up, and that the sign-up check cannot be switched on without its keys.
 *
 * Use cases:
 * - someone registers and does not enter their code: staff find them on /console/signups, the page will not approve them
 *   without a reason, and with one it makes the account (credits given once, the page says to confirm the person out of
 *   band, and the password typed at sign-up does not sign in)
 * - the approved learner's sign-in page says the email was marked by staff and that they have no way to sign in yet, offers
 *   no "mark verified" for an account that already is, and the API refuses it (a code is never part of the page: that is
 *   proved by tests/console/test_learner_verification.py)
 * - /console/abuse shows the numbers and the sign-up check is off, and cannot be switched on in this stack (no keys)
 * - the Learners list keeps to a sign-in state: an account from before verification shows under Legacy, one set back to
 *   unverified under Not verified, each with its pill, and the chips change the address
 * - a learner gets the page that does not exist for each of the new pages, and the API's 404
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Seed } from "../support/seed";

async function staffPage(browser: Browser): Promise<{ page: Page; api: Api }> {
  const page = await (await browser.newContext()).newPage();
  const api = new Api(page);
  expect((await api.call("POST", "/auth/login", { email: E2E.STAFF_EMAIL, password: E2E.STAFF_PASSWORD })).status).toBe(200);
  return { page, api };
}

const REASON = "Spoke to the student's teacher at school";

test("staff approve a sign-up that is waiting for its code: it needs a reason and leaves an account with no password", async ({ browser }) => {
  const email = E2E.email("waiting");
  const visitor = await (await browser.newContext()).newPage();
  const registered = await new Api(visitor).call("POST", "/auth/register", { name: "Wanda Waiting", email, password: E2E.PASSWORD, accept_terms: true });
  expect(registered.status).toBe(202);

  const { page, api } = await staffPage(browser);
  await page.goto(`/console/signups?q=${encodeURIComponent(email)}`);
  const row = page.getByRole("row", { name: new RegExp(email) });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Approve…" }).click();

  const form = page.getByRole("form", { name: `Approve ${email}` });
  await form.getByRole("button", { name: "Approve and make the account" }).click();
  await expect(form.getByText(/at least 10 characters/i).first()).toBeVisible(); // no reason, no account
  expect((await api.call("GET", `/console/learners?q=${encodeURIComponent(email)}`)).body.results).toHaveLength(0);

  await form.getByLabel("Reason (required)").fill(REASON);
  await form.getByRole("button", { name: "Approve and make the account" }).click();
  const approved = page.getByRole("region", { name: "Approved" });
  await expect(approved).toContainText("out of band");
  await expect(approved).toContainText("Google");

  const found = (await api.call("GET", `/console/learners?q=${encodeURIComponent(email)}`)).body.results;
  expect(found).toHaveLength(1);
  const wallet = await api.call("GET", `/console/learners/${found[0].id}/wallet`);
  expect(wallet.body.buckets.filter((bucket: { source: string }) => bucket.source === "signup")).toHaveLength(1); // credits, once

  const typed = await new Api(visitor).call("POST", "/auth/login", { email, password: E2E.PASSWORD });
  expect(typed.status).toBe(401); // the password typed at sign-up was never copied
  await expect(page.getByRole("row", { name: new RegExp(email) })).toHaveCount(0);
});

test("the approved learner's sign-in page says staff vouched for them and never shows a code", async ({ browser }) => {
  const email = E2E.email("vouched");
  const visitor = await (await browser.newContext()).newPage();
  await new Api(visitor).call("POST", "/auth/register", { name: "Vera Vouched", email, password: E2E.PASSWORD, accept_terms: true });
  const { page, api } = await staffPage(browser);
  const waiting = (await api.call("GET", `/console/signups?q=${encodeURIComponent(email)}`)).body.results[0];
  expect((await api.call("POST", `/console/signups/${waiting.id}/approve`, { reason: REASON })).status).toBe(200);
  const learner = (await api.call("GET", `/console/learners?q=${encodeURIComponent(email)}`)).body.results[0];

  await page.goto(`/console/learners/${learner.id}/verification`);

  await expect(page.getByRole("heading", { name: "Vera Vouched" })).toBeVisible();
  await expect(page.getByText("Marked by staff").first()).toBeVisible();
  await expect(page.getByText("No way to sign in yet").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Mark verified" })).toHaveCount(0); // already verified
  const refused = await api.call("POST", `/console/learners/${learner.id}/verification/mark-verified`, { reason: REASON });
  expect(refused.status).toBe(409);
  expect(refused.body.code).toBe("already_verified");
});

test("the abuse board shows the numbers, and the sign-up check cannot be switched on without its keys", async ({ browser }) => {
  const { page, api } = await staffPage(browser);
  await page.goto("/console/abuse");

  await expect(page.getByRole("heading", { name: "Sign-up abuse" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Accounts made" })).toBeVisible();
  await expect(page.getByRole("table", { name: /Sign-up activity per day/ })).toBeVisible();
  const toggle = page.getByRole("switch", { name: "Ask visitors to pass a check" });
  await expect(toggle).not.toBeChecked();
  await expect(toggle).toBeDisabled();
  await expect(page.getByText(/Not set up: add TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY/)).toBeVisible();

  const refused = await api.call("PUT", "/console/auth-settings", { captcha_enabled: true });
  expect(refused.status).toBe(409);
  expect(refused.body.code).toBe("captcha_not_configured");
  expect((await new Api(page).call("GET", "/auth/captcha")).body).toEqual({ enabled: false, site_key: "" });
});

test("a learner gets the page that does not exist for each new console page, and the API's 404", async ({ browser }) => {
  const learner = await (await browser.newContext()).newPage();
  const api = new Api(learner);
  await api.signUp(E2E.email("stranger"), E2E.PASSWORD);

  for (const path of ["/console/signups", "/console/abuse", "/console/learners/00000000-0000-0000-0000-000000000000/verification"]) {
    await learner.goto(path);
    await expect(learner.getByText(/couldn.t find that page/i)).toBeVisible();
  }
  for (const path of ["/console/signups", "/console/abuse", "/console/auth-settings"]) {
    expect((await api.call("GET", path)).status).toBe(404);
  }
});

test("the Learners list keeps to a sign-in state: legacy and not verified, with their counts", async ({ browser }) => {
  const legacy = E2E.email("legacy-list");
  const unverified = E2E.email("unverified-list");
  Seed.signInState(legacy, E2E.PASSWORD, "legacy");
  Seed.signInState(unverified, E2E.PASSWORD, "unverified");
  const { page, api } = await staffPage(browser);

  await page.goto("/console/learners");
  const chips = page.getByRole("group", { name: "Sign-in" });
  await expect(chips.getByRole("button", { name: /^Everyone/ })).toBeVisible();
  await chips.getByRole("button", { name: /^Legacy/ }).click();
  await expect(page).toHaveURL(/verification=legacy/);
  await expect(page.getByRole("row", { name: new RegExp(legacy) })).toContainText("Legacy");
  await expect(page.getByRole("row", { name: new RegExp(unverified) })).toHaveCount(0);

  await chips.getByRole("button", { name: /^Not verified/ }).click();
  await expect(page).toHaveURL(/verification=unverified/);
  await expect(page.getByRole("row", { name: new RegExp(unverified) })).toContainText("Not verified");
  await expect(page.getByRole("row", { name: new RegExp(legacy) })).toHaveCount(0);

  const summary = (await api.call("GET", "/console/learners?verification=locked")).body.summary;
  expect(summary.legacy).toBeGreaterThanOrEqual(1);
  expect(summary.unverified).toBeGreaterThanOrEqual(1);
  expect((await api.call("GET", "/console/learners?verification=nonsense")).status).toBe(400);
});
