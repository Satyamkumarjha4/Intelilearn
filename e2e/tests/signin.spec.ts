/**
 * Signing up with a code (phase 11.1). A person who creates an account is sent a six-digit code and has no account until
 * they enter it in the browser that asked; only then are there credits. The code comes from the throwaway stack's outbox, the
 * way a learner would read it in their inbox. An account from before verification existed keeps its sign-in with no code
 * until `require_reverification` is run (the launch step), and then it is asked for one. A forgotten password is reset the same
 * way (phase 11.2): a code from the inbox, a new password, signed in, and every older session ended. Continue with Google
 * (phase 11.3) runs against the stack's stand-in provider: a new person has no account until the last step, an account made
 * with a code is linked, one nobody proved is taken over, and an unconfirmed email and a staff account are refused.
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

test("a forgotten password is reset with an emailed code: signed in, the old password and the old session stop working", async ({ page, browser }) => {
  const email = E2E.email("reset");
  await new Api(page).signUp(email, E2E.PASSWORD);
  const oldRefresh = (await page.context().cookies()).find((cookie) => cookie.name === "lc_refresh")?.value;
  expect(oldRefresh).toBeTruthy();
  await page.context().clearCookies(); // a person who cannot sign in

  await page.goto("/auth");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await page.waitForURL(/\/auth\/forgot/);
  await page.getByLabel("Email").fill(email);
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/auth\/reset/);
  await expect(page.getByText(`If ${email} has an account`)).toBeVisible(); // never says it does

  const code = await Outbox.code(page.request, email, "reset_code");
  const newPassword = "A-new-passphrase-42";
  await page.getByLabel("6-digit code").fill(code);
  await page.getByLabel("New password", { exact: true }).fill(newPassword);
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/lessons/); // signed in, and the profile was already complete

  const elsewhere = await (await browser.newContext()).newPage();
  const other = new Api(elsewhere);
  expect((await other.call("POST", "/auth/login", { email, password: E2E.PASSWORD })).status).toBe(401);
  await elsewhere.context().addCookies([{ name: "lc_refresh", value: oldRefresh!, domain: new URL(page.url()).hostname, path: "/api/auth" }]);
  expect((await other.call("POST", "/auth/refresh")).status).toBe(401); // the old session is over
  expect((await other.call("POST", "/auth/login", { email, password: newPassword })).status).toBe(200);
});

test("asking for a reset for an address nobody has looks exactly the same, and sends nothing", async ({ page }) => {
  const email = E2E.email("nobody");
  await page.goto("/auth/forgot");
  await page.getByLabel("Email").fill(email);
  await page.locator("form button[type=submit]").click();

  await page.waitForURL(/\/auth\/reset/);
  await expect(page.getByText(`If ${email} has an account`)).toBeVisible();
  expect(await Outbox.count(page.request, email, "reset_code")).toBe(0);
});

// --- Continue with Google (phase 11.3), with the stack's stand-in provider: it answers the redirect itself with whoever the
// address names, and the real state check, linking rules, cookies and proxy all run. ---

/** The address that signs in with the stand-in provider as `who`. */
function googleAs(who: { subject: string; email: string; email_verified?: boolean; name?: string }): string {
  return `/api/auth/oauth/fake/start?fake=${encodeURIComponent(JSON.stringify({ name: "Google Person", ...who }))}`;
}

const unique = (label: string) => `${label}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

test("a new person has no account and no credits until the last step, and exactly 30 after", async ({ page }) => {
  const email = E2E.email("google-new");
  await page.goto(googleAs({ subject: unique("sub"), email }));

  await page.waitForURL(/\/auth\/finish/);
  await expect(page.getByRole("heading", { name: "One last step" })).toBeVisible();
  await expect(page.getByLabel("Email from Google")).toHaveValue(email);
  const api = new Api(page);
  expect((await api.call("GET", "/auth/me")).status).toBe(401); // nothing exists yet
  expect((await api.call("GET", "/credits/wallet")).status).toBe(401);

  await page.locator("form button[type=submit]").click();
  await expect(page.locator("#accept_terms-error")).toBeVisible(); // not without agreeing to the terms
  await page.locator("input[name=accept_terms]").check();
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/onboarding/);

  expect((await api.call("GET", "/credits/wallet")).body).toMatchObject({ balance: 30, buckets: [{ source: "signup", remaining: 30 }] });
});

test("the Continue with Google button starts it, from the sign-in page", async ({ page }) => {
  await page.goto("/auth");

  await page.getByRole("link", { name: "Continue with Google (test)" }).click();

  await page.waitForURL(/\/auth\/finish/);
  await expect(page.getByLabel("Name")).toHaveValue("Fake Person");
});

test("an account made with a code is linked: no second account and no second grant", async ({ page }) => {
  const email = E2E.email("google-linked");
  const api = new Api(page);
  await api.signUp(email, E2E.PASSWORD);
  await page.context().clearCookies();

  await page.goto(googleAs({ subject: unique("sub"), email: email.toUpperCase().replace("@EXAMPLE.COM", "@example.com") }));

  await page.waitForURL(/\/lessons/); // signed in, and the profile was already complete
  expect((await api.call("GET", "/auth/me")).body.email).toBe(email);
  expect((await api.call("GET", "/credits/wallet")).body).toMatchObject({ balance: 30 });
  const again = await (await page.context().browser()!.newContext()).newPage();
  expect((await new Api(again).call("POST", "/auth/login", { email, password: E2E.PASSWORD })).status).toBe(200); // the password still works
});

test("an account nobody proved is taken over: its old password and its old session stop working", async ({ page, browser }) => {
  const email = E2E.email("google-takeover");
  Seed.legacyAccount(email, E2E.PASSWORD, { reverify: true });
  const thief = await (await browser.newContext()).newPage();
  expect((await new Api(thief).call("POST", "/auth/login", { email, password: E2E.PASSWORD })).status).toBe(403); // asks for a code

  await page.goto(googleAs({ subject: unique("sub"), email }));

  await page.waitForURL(/\/(onboarding|lessons)/); // the person who proved the inbox is in
  const api = new Api(page);
  expect((await api.call("GET", "/credits/wallet")).body).toMatchObject({ balance: 30 });
  const elsewhere = await (await browser.newContext()).newPage();
  expect((await new Api(elsewhere).call("POST", "/auth/login", { email, password: E2E.PASSWORD })).status).toBe(401);
});

test("an email Google has not confirmed is refused, with words", async ({ page }) => {
  await page.goto(googleAs({ subject: unique("sub"), email: E2E.email("google-unconfirmed"), email_verified: false }));

  await page.waitForURL(/\/auth\?error=email_not_verified/);
  await expect(page.getByText("Google hasn't confirmed that email address")).toBeVisible();
  expect((await new Api(page).call("GET", "/auth/me")).status).toBe(401);
});

test("a staff account is never signed in or taken over by Google", async ({ page }) => {
  await page.goto(googleAs({ subject: unique("sub"), email: E2E.STAFF_EMAIL }));

  await page.waitForURL(/\/auth\?error=sign_in_failed/);
  await expect(page.getByText("We couldn't sign you in that way.")).toBeVisible();
  expect((await new Api(page).call("GET", "/auth/me")).status).toBe(401);
});

test("a person who waits too long at the last step is told so and sent back", async ({ page }) => {
  await page.goto(googleAs({ subject: unique("sub"), email: E2E.email("google-late") }));
  await page.waitForURL(/\/auth\/finish/);

  await page.context().clearCookies(); // the signed ticket is gone, as it is after its few minutes
  await page.reload();

  await expect(page.getByText("That took too long.")).toBeVisible();
  await page.getByRole("button", { name: "Back to sign in" }).click();
  await expect(page).toHaveURL(/\/auth$/);
});
