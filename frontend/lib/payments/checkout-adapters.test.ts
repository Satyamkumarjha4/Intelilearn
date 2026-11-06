/**
 * Unit under test: `CheckoutAdapters` and `RedirectCheckout`, which take a learner through a provider's checkout without
 * the screen knowing which provider it is (credits plan §9.4).
 *
 * Why: a provider with a third style of checkout must be one new class and one line, and no component may branch on a
 * provider. And whichever way someone pays, the adapter must only send them to pay: it never says the payment was made.
 *
 * Use cases:
 * - a redirect checkout goes to its link; a redirect adapter given a client checkout says what it cannot take
 * - a client checkout goes to the adapter it names, with the checkout and where to come back to
 * - an adapter that was never registered is a clear error naming it
 * - registering a new adapter is all a new style needs
 */
import { describe, expect, test } from "bun:test";

import { CheckoutAdapters, RedirectCheckout, UnknownCheckout, type CheckoutAdapter } from "./checkout-adapters";
import type { Checkout } from "./types";

const redirect: Checkout = { kind: "redirect", redirect_url: "https://pay.example/session/1" };
const client: Checkout = { kind: "client", adapter: "onpage", client: { order_id: "o1" } };

describe("RedirectCheckout", () => {
  test("goes to the link it was given", () => {
    const went: string[] = [];

    new RedirectCheckout((url) => went.push(url)).begin(redirect);

    expect(went).toEqual(["https://pay.example/session/1"]);
  });

  test("will not take a checkout that is not a redirect", () => {
    expect(() => new RedirectCheckout(() => {}).begin(client)).toThrow(UnknownCheckout);
  });
});

describe("CheckoutAdapters", () => {
  test("a redirect checkout goes to the redirect adapter, whatever the provider", () => {
    const went: string[] = [];
    const adapters = new CheckoutAdapters(new RedirectCheckout((url) => went.push(url)));

    adapters.begin(redirect, "/buy/return?order=o1");

    expect(went).toEqual(["https://pay.example/session/1"]);
  });

  test("a client checkout goes to the adapter it names, with where to come back to", () => {
    const seen: unknown[] = [];
    const onpage: CheckoutAdapter = { begin: (checkout, returnTo) => void seen.push([checkout, returnTo]) };
    const adapters = new CheckoutAdapters().register("onpage", onpage);

    adapters.begin(client, "/buy/return?order=o1");

    expect(seen).toEqual([[client, "/buy/return?order=o1"]]);
  });

  test("an adapter nobody registered is a clear error that names it", () => {
    const adapters = new CheckoutAdapters();

    expect(() => adapters.begin(client, "/x")).toThrow('There is no checkout for "onpage".');
    try {
      adapters.begin(client, "/x");
    } catch (error) {
      expect(error).toBeInstanceOf(UnknownCheckout);
      expect((error as UnknownCheckout).name).toBe("UnknownCheckout");
    }
  });

  test("a new style is one register call", () => {
    const adapters = new CheckoutAdapters();
    expect(() => adapters.for(client)).toThrow();

    adapters.register("onpage", { begin: () => {} });

    expect(() => adapters.for(client)).not.toThrow();
  });
});
