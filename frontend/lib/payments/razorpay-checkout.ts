import { CheckoutUnavailable, UnknownCheckout, type CheckoutAdapter, type CheckoutEnd } from "./checkout-contract";
import { ScriptLoader } from "./script-loader";
import type { Checkout } from "./types";

type RazorpayOptions = Record<string, unknown> & { handler: () => void; modal: Record<string, unknown> & { ondismiss: () => void } };
export type RazorpayConstructor = new (options: RazorpayOptions) => { open(): void };

/**
 * Razorpay's on-page checkout (credits plan §9.4, D18). The server made the order and hands over only public parameters
 * (the key id, Razorpay's order id, the amount, a name, whether to allow a retry); this loads Razorpay's script when it is
 * first needed, opens the window with them, and does one of two things:
 *
 * - the learner **pays**: the window's success callback only sends the browser to the return page. It is given a payment
 *   id and a signature, and ignores both: the server hears of the payment from Razorpay itself and the page asks the
 *   server (T24), so nothing a browser says can grant anything;
 * - the learner **closes** the window: the promise resolves `closed`, so the buy page is theirs again. The order stays
 *   waiting and the server lets it go later.
 */
export class RazorpayCheckout implements CheckoutAdapter {
  static readonly NAME = "razorpay";
  static readonly SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

  constructor(
    private readonly scripts: ScriptLoader = new ScriptLoader(),
    private readonly go: (url: string) => void = (url) => window.location.assign(url),
    private readonly razorpay: () => RazorpayConstructor | undefined = () => (window as { Razorpay?: RazorpayConstructor }).Razorpay,
  ) {}

  async begin(checkout: Checkout, returnTo: string): Promise<CheckoutEnd> {
    if (checkout.kind !== "client" || checkout.adapter !== RazorpayCheckout.NAME) {
      throw new UnknownCheckout(checkout.kind === "client" ? checkout.adapter : checkout.kind);
    }
    await this.scripts.load(RazorpayCheckout.SCRIPT, () => this.razorpay() !== undefined);
    const Razorpay = this.razorpay();
    if (!Razorpay) throw new CheckoutUnavailable("The payment window did not start.");

    return new Promise<CheckoutEnd>((resolve) => {
      let paid = false;
      const options: RazorpayOptions = {
        ...checkout.client,
        handler: () => {
          paid = true;
          this.go(returnTo);
        },
        modal: {
          ...(checkout.client.modal as Record<string, unknown> | undefined),
          ondismiss: () => {
            if (!paid) resolve("closed"); // after a payment the page is already on its way to the return page
          },
        },
      };
      new Razorpay(options).open();
    });
  }
}
