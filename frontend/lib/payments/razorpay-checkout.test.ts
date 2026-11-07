/**
 * Unit under test: `RazorpayCheckout`, the adapter that opens Razorpay's on-page checkout, and its place in the
 * `CheckoutAdapters` registry (credits plan §9.4, T24).
 *
 * Why: this is the only code in the browser that sits beside a payment, so what it must NOT do matters most. It never
 * tells the server a payment was made (the server hears from Razorpay and the return page asks): on completion it only
 * navigates to the return page, whatever the window gave it. It loads Razorpay's script only when someone is paying, and
 * once. A learner who shuts the window must get the buy page back, not a button stuck on "working".
 *
 * Use cases:
 * - it takes only a client checkout that names `razorpay`; anything else is `UnknownCheckout`
 * - the script is loaded when a payment begins and not before, and once however many payments begin
 * - the window is opened with the server's parameters as they came (key id, order id, amount, retry off…), plus the
 *   success callback and the close callback, and nothing else
 * - paying only navigates to the return page: the payment id and signature the window gives are not read, kept or sent
 * - closing the window resolves `closed` and navigates nowhere; closing after paying does not claim the learner is back
 * - a script that cannot load, or leaves no `Razorpay`, is `CheckoutUnavailable` and opens nothing
 * - the registry: a `razorpay` client checkout goes to this adapter, a redirect goes to the redirect one
 * - a window that would not open is told to the learner in plain words, with nothing charged
 */
import { describe, expect, test } from "bun:test";

import { CheckoutAdapters, RedirectCheckout } from "./checkout-adapters";
import { CheckoutUnavailable, UnknownCheckout } from "./checkout-contract";
import { checkoutAdapters } from "./checkout-adapters";
import { PaymentWords } from "./payment-words";
import { RazorpayCheckout, type RazorpayConstructor } from "./razorpay-checkout";
import { ScriptLoader, type ScriptInjector } from "./script-loader";
import type { Checkout } from "./types";

const PARAMS = {
  key: "rzp_test_publicid",
  order_id: "order_Abc123",
  amount: 49900,
  currency: "INR",
  name: "Socra",
  description: "Weekly Pro",
  prefill: { email: "a@example.com" },
  retry: { enabled: false },
};
const razorpay: Checkout = { kind: "client", adapter: "razorpay", client: PARAMS };

/** A page whose Razorpay script the test controls: `loads` counts injections, and the global appears when it loads. */
function page({ works = true, fails = false }: { works?: boolean; fails?: boolean } = {}) {
  const state = {
    loads: 0,
    went: [] as string[],
    opened: [] as Record<string, unknown>[],
    present: false,
    open: [] as (() => void)[],
  };
  const Fake = class {
    constructor(readonly options: Record<string, unknown>) {
      state.opened.push(options);
    }
    open() {
      state.open.push(() => {});
    }
  };
  const inject: ScriptInjector = (_src, ok, fail) => {
    state.loads++;
    if (fails) return fail();
    if (works) state.present = true;
    ok();
  };
  const checkout = new RazorpayCheckout(
    new ScriptLoader(inject),
    (url) => state.went.push(url),
    () => (state.present ? (Fake as unknown as RazorpayConstructor) : undefined),
  );
  return { state, checkout };
}

const handlerOf = (state: ReturnType<typeof page>["state"]) => state.opened[0].handler as (r?: unknown) => void;
const modalOf = (state: ReturnType<typeof page>["state"]) => state.opened[0].modal as { ondismiss: () => void };

describe("RazorpayCheckout", () => {
  test("takes only a client checkout that names razorpay", async () => {
    const { checkout } = page();

    await expect(checkout.begin({ kind: "redirect", redirect_url: "https://x" }, "/r")).rejects.toBeInstanceOf(UnknownCheckout);
    await expect(checkout.begin({ kind: "client", adapter: "other", client: {} }, "/r")).rejects.toBeInstanceOf(UnknownCheckout);
  });

  test("loads the script when a payment begins, not before, and once", async () => {
    const { state, checkout } = page();
    expect(state.loads).toBe(0);

    void checkout.begin(razorpay, "/buy/return?order=o1");
    await Promise.resolve();
    await Promise.resolve();
    void checkout.begin(razorpay, "/buy/return?order=o2");
    await Promise.resolve();
    await Promise.resolve();

    expect(state.loads).toBe(1);
    expect(state.opened).toHaveLength(2);
  });

  test("opens the window with the server's parameters, a success callback and a close callback", async () => {
    const { state, checkout } = page();

    void checkout.begin(razorpay, "/buy/return?order=o1");
    await Promise.resolve();
    await Promise.resolve();

    expect(state.opened).toHaveLength(1);
    expect(state.opened[0]).toMatchObject(PARAMS);
    expect(Object.keys(state.opened[0]).sort()).toEqual([...Object.keys(PARAMS), "handler", "modal"].sort());
    expect(Object.keys(modalOf(state))).toEqual(["ondismiss"]);
    expect(state.open).toHaveLength(1);
  });

  test("paying only navigates to the return page, whatever the window gives", async () => {
    const { state, checkout } = page();
    void checkout.begin(razorpay, "/buy/return?order=o1");
    await Promise.resolve();
    await Promise.resolve();

    handlerOf(state)({ razorpay_payment_id: "pay_1", razorpay_order_id: "order_Abc123", razorpay_signature: "sig" });

    expect(state.went).toEqual(["/buy/return?order=o1"]); // no payment id, no signature, no state in the address
  });

  test("closing the window resolves `closed` and goes nowhere", async () => {
    const { state, checkout } = page();
    const ended = checkout.begin(razorpay, "/buy/return?order=o1");
    await Promise.resolve();
    await Promise.resolve();

    modalOf(state).ondismiss();

    expect(await ended).toBe("closed");
    expect(state.went).toEqual([]);
  });

  test("closing after paying does not say the learner is back, because the page is on its way", async () => {
    const { state, checkout } = page();
    let settled = false;
    void checkout.begin(razorpay, "/buy/return?order=o1").then(() => (settled = true));
    await Promise.resolve();
    await Promise.resolve();

    handlerOf(state)();
    modalOf(state).ondismiss();
    await Promise.resolve();

    expect(settled).toBe(false);
    expect(state.went).toEqual(["/buy/return?order=o1"]);
  });

  test("a script that cannot be loaded is CheckoutUnavailable and nothing is opened", async () => {
    const { state, checkout } = page({ fails: true });

    await expect(checkout.begin(razorpay, "/r")).rejects.toBeInstanceOf(CheckoutUnavailable);

    expect(state.opened).toHaveLength(0);
  });

  test("a script that leaves no Razorpay behind is CheckoutUnavailable", async () => {
    const { state, checkout } = page({ works: false });

    await expect(checkout.begin(razorpay, "/r")).rejects.toBeInstanceOf(CheckoutUnavailable);

    expect(state.opened).toHaveLength(0);
  });
});

describe("the registry", () => {
  test("a razorpay client checkout goes to the Razorpay adapter and a redirect to the redirect one, by the session", () => {
    expect(checkoutAdapters.for(razorpay)).toBeInstanceOf(RazorpayCheckout);
    expect(checkoutAdapters.for({ kind: "redirect", redirect_url: "https://pay.example/1" })).toBeInstanceOf(RedirectCheckout);
  });

  test("a client checkout for an adapter nobody registered is still a clear error", () => {
    expect(() => checkoutAdapters.for({ kind: "client", adapter: "paypal", client: {} })).toThrow(UnknownCheckout);
  });

  test("a registry that was never given Razorpay does not have it (the adapter is a registry line, not a branch)", () => {
    expect(() => new CheckoutAdapters().for(razorpay)).toThrow(UnknownCheckout);
  });
});

describe("the words", () => {
  test("a window that would not open says nothing was charged and to try again, in no provider's words", () => {
    const words = PaymentWords.refusal(new CheckoutUnavailable("The payment window could not be loaded."));

    expect(words).toContain("Nothing was charged");
    expect(words.toLowerCase()).not.toMatch(/razorpay|script|gateway|webhook/);
  });
});
