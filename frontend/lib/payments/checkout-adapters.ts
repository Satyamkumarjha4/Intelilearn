import type { Checkout } from "./types";

/** One way of taking a learner through a provider's checkout. It never says the payment was made: the server hears that
 *  from the provider, and the return page asks the server. */
export interface CheckoutAdapter {
  begin(checkout: Checkout, returnTo: string): void | Promise<void>;
}

/** The checkout names an adapter this build does not have. */
export class UnknownCheckout extends Error {
  constructor(readonly name: string) {
    super(`There is no checkout for "${name}".`);
    this.name = "UnknownCheckout";
  }
}

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
 * one `register` line (Razorpay's on-page checkout arrives with its adapter). Components call `begin` and never branch.
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
  begin(checkout: Checkout, returnTo: string): void | Promise<void> {
    return this.for(checkout).begin(checkout, returnTo);
  }
}

export const checkoutAdapters = new CheckoutAdapters();
