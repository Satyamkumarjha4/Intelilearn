import type { Checkout } from "./types";

/** What an adapter reports when it is done with the learner: `closed` is the learner shutting the provider's own window
 *  without paying, so the screen is theirs again. An adapter that sends the browser away has nothing to report, because
 *  the page is gone. */
export type CheckoutEnd = "closed";

/** One way of taking a learner through a provider's checkout. It never says the payment was made: the server hears that
 *  from the provider, and the return page asks the server. */
export interface CheckoutAdapter {
  begin(checkout: Checkout, returnTo: string): void | Promise<CheckoutEnd | void>;
}

/** The checkout names an adapter this build does not have. */
export class UnknownCheckout extends Error {
  constructor(readonly name: string) {
    super(`There is no checkout for "${name}".`);
    this.name = "UnknownCheckout";
  }
}

/** The provider's checkout could not be opened (its script did not load, or did not do what it should). Nothing was
 *  charged, and trying again is safe. */
export class CheckoutUnavailable extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CheckoutUnavailable";
  }
}
