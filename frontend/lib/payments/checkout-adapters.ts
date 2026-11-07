import { UnknownCheckout, type CheckoutAdapter, type CheckoutEnd } from "./checkout-contract";
import { RazorpayCheckout } from "./razorpay-checkout";
import type { Checkout } from "./types";

export { CheckoutUnavailable, UnknownCheckout, type CheckoutAdapter, type CheckoutEnd } from "./checkout-contract";

/** Sends the browser to the provider's own page. */
export class RedirectCheckout implements CheckoutAdapter {
  constructor(private readonly go: (url: string) => void = (url) => window.location.assign(url)) {}

  begin(checkout: Checkout): void {
    if (checkout.kind !== "redirect") throw new UnknownCheckout(checkout.kind);
    this.go(checkout.redirect_url);
  }
}

/**
 * Chooses how to take someone through a checkout by what the server returned, never by which provider it is: a redirect goes
 * to `RedirectCheckout`, and a `client` checkout goes to the adapter it names. A provider with a third style adds a class and
 * one `register` line (Razorpay's on-page checkout is the first). Components call `begin` and never branch.
 */
export class CheckoutAdapters {
  private readonly clients = new Map<string, CheckoutAdapter>();

  constructor(private readonly redirect: CheckoutAdapter = new RedirectCheckout()) {}

  register(name: string, adapter: CheckoutAdapter): this {
    this.clients.set(name, adapter);
    return this;
  }

  for(checkout: Checkout): CheckoutAdapter {
    if (checkout.kind === "redirect") return this.redirect;
    const adapter = this.clients.get(checkout.adapter);
    if (!adapter) throw new UnknownCheckout(checkout.adapter);
    return adapter;
  }

  /** Take the learner to pay. `returnTo` is where the provider brings them back (the return page, which only asks). */
  begin(checkout: Checkout, returnTo: string): void | Promise<CheckoutEnd | void> {
    return this.for(checkout).begin(checkout, returnTo);
  }
}

export const checkoutAdapters = new CheckoutAdapters().register(RazorpayCheckout.NAME, new RazorpayCheckout());
