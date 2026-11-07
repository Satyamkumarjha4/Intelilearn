/**
 * Buying credits through Razorpay's real test mode (credits plan phase 10.8, section 13.4). Run by `make e2e-payments`;
 * skipped by `make e2e`, which needs no key and no network.
 *
 * Why: the fake gateway proves our side of buying, but not that Razorpay's own checkout window, a real order and the status
 * fetch fit together. Razorpay's checkout opens on our page (an iframe), so this also shows the on-page adapter: that the
 * script loads only when someone pays, that the window opens with the server's parameters, and that completing it only
 * brings the learner to the return page, which asks the server, which asks Razorpay. No public address is needed, so no
 * tunnel: webhooks to localhost need one and are an optional extra described in docs/getting-started/local-setup.md.
 *
 * Use cases:
 * - one-time credits: choose an amount, pay in Razorpay's window with the test UPI id success@razorpay, come back, and the
 *   balance rises (the order is fulfilled with a payment reference) without any webhook
 * - closing the window without paying leaves the learner on /buy with the order waiting and nothing granted
 *
 * Needs the stack started as `make e2e-payments` does (Razorpay the only way to pay) and RAZORPAY_KEY_ID set to a test-mode
 * key (`E2E_RAZORPAY=1` is set by that target when it is). The selectors inside Razorpay's window are its own and are not
 * ours to keep stable: this spec has not yet been run against a live test account.
 */
import { expect, test, type Page } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";

test.skip(!process.env.E2E_RAZORPAY, "needs RAZORPAY_KEY_ID=rzp_test_... in .env and `make e2e-payments`");

async function balance(api: Api): Promise<number> {
  return (await api.call("GET", "/credits/wallet")).body.balance;
}

async function startPaying(page: Page) {
  await page.goto("/buy");
  await expect(page.getByText("How would you like to pay?")).toHaveCount(0); // Razorpay is the only way on this stack
  await expect(page.locator('script[src*="checkout.razorpay.com"]')).toHaveCount(0); // not loaded until someone pays
  await page.getByTestId("chip-100").click();
  await page.getByTestId("buy-one_time").click();
  const frame = page.frameLocator("iframe.razorpay-checkout-frame");
  await expect(page.locator('script[src*="checkout.razorpay.com"]')).toHaveCount(1);
  return frame;
}

test("one-time credits bought through Razorpay's test mode arrive by the return page's status fetch", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("razorpay"), E2E.PASSWORD);

  const frame = await startPaying(page);
  const phone = frame.getByPlaceholder(/mobile|phone/i).first();
  if (await phone.isVisible({ timeout: 30_000 }).catch(() => false)) {
    await phone.fill("9876543210");
    await frame.getByRole("button", { name: /continue/i }).first().click();
  }
  await frame.getByText(/^UPI$/i).first().click({ timeout: 30_000 });
  await frame.getByPlaceholder(/upi id|vpa/i).first().fill("success@razorpay");
  await frame.getByRole("button", { name: /pay|verify/i }).first().click();

  await page.waitForURL(/\/buy\/return\?order=/, { timeout: 90_000 });
  const orderId = new URL(page.url()).searchParams.get("order")!;
  await expect(page.getByTestId("return-headline")).toHaveText("Your credits are here", { timeout: 150_000 });

  const order = (await api.call("GET", `/payments/orders/${orderId}`)).body;
  expect(order).toMatchObject({ status: "fulfilled", amount_paise: 10000, credits: 100 });
  expect(await balance(api)).toBe(130);
});

test("closing Razorpay's window without paying leaves the learner on the buy page with nothing granted", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("razorpay-close"), E2E.PASSWORD);

  const frame = await startPaying(page);
  await frame.locator("body").waitFor({ timeout: 30_000 });
  await page.keyboard.press("Escape"); // Razorpay's window closes on Escape (its `escape` option defaults to true)
  await page.locator("iframe.razorpay-checkout-frame").waitFor({ state: "detached", timeout: 30_000 }).catch(() => {});

  await expect(page).toHaveURL(/\/buy$/);
  await expect(page.getByTestId("buy-one_time")).toBeEnabled();
  expect(await balance(api)).toBe(30);
});
