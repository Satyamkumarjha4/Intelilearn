/**
 * Buying credits through Stripe's real test mode (credits plan phase 10.7, section 13.4). Run by `make e2e-payments`;
 * skipped by `make e2e`, which needs no key and no network.
 *
 * Why: the fake gateway proves our side of buying, but not that Stripe's own page, a real Checkout Session and the status
 * fetch fit together. The learner pays with Stripe's test card, comes back to the site, and the page confirms the payment
 * by asking the server, which asks Stripe. No public address is needed, so no tunnel: a forwarded webhook (the Stripe CLI)
 * is an optional extra described in docs/getting-started/local-setup.md.
 *
 * Use cases:
 * - one-time credits: choose an amount, pay on Stripe's page with the test card 4242 4242 4242 4242, come back, and the
 *   balance rises (the order is fulfilled with a payment reference) without any webhook
 *
 * Needs the stack started as `make e2e-payments` does (Stripe the only way to pay) and STRIPE_SECRET_KEY set to a
 * test-mode key (`E2E_STRIPE=1` is set by that target when it is).
 */
import { expect, test, type Page } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";

test.skip(!process.env.E2E_STRIPE, "needs STRIPE_SECRET_KEY=sk_test_... in .env and `make e2e-payments`");

async function balance(api: Api): Promise<number> {
  return (await api.call("GET", "/credits/wallet")).body.balance;
}

/** Stripe's hosted Checkout page. Its fields have kept these ids; the placeholders are the fallback if they change. */
async function payWithTestCard(page: Page) {
  await page.waitForURL(/checkout\.stripe\.com/, { timeout: 60_000 });
  const field = (id: string, placeholder: RegExp) => page.locator(`#${id}`).or(page.getByPlaceholder(placeholder)).first();
  await field("cardNumber", /1234 1234 1234 1234/).fill("4242424242424242");
  await field("cardExpiry", /MM \/ YY/).fill("1234");
  await field("cardCvc", /CVC/).fill("123");
  const name = page.locator("#billingName").or(page.getByPlaceholder(/full name on card/i)).first();
  if (await name.isVisible().catch(() => false)) await name.fill("Socra Test");
  await page.locator(".SubmitButton, [data-testid='hosted-payment-submit-button']").first().click();
}

test("one-time credits bought through Stripe's test mode arrive by the return page's status fetch", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("stripe"), E2E.PASSWORD);

  await page.goto("/buy");
  await expect(page.getByText("How would you like to pay?")).toHaveCount(0); // Stripe is the only way on this stack
  await page.getByTestId("chip-100").click();
  await page.getByTestId("buy-one_time").click();
  await payWithTestCard(page);

  await page.waitForURL(/\/buy\/return\?order=/, { timeout: 90_000 });
  const orderId = new URL(page.url()).searchParams.get("order")!;
  await expect(page.getByTestId("return-headline")).toHaveText("Your credits are here", { timeout: 150_000 });

  const order = (await api.call("GET", `/payments/orders/${orderId}`)).body;
  expect(order).toMatchObject({ status: "fulfilled", amount_paise: 10000, credits: 100 });
  expect(await balance(api)).toBe(130);
});
