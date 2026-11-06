import { createHmac } from "node:crypto";

import type { Page } from "@playwright/test";

type Reply = { status: number; body: any };
type Order = { id: string; amount_paise: number };

/** The payment provider, played by the test: it signs a callback with the fake gateway's secret and sends it to the
 *  webhook through the **frontend's** address, as a real provider would reach the site, which proves the proxy keeps the raw
 *  body and the signature header. */
export class Provider {
  static readonly SECRET = process.env.PAYMENT_FAKE_GATEWAY_SECRET ?? "e2e-fake-gateway-secret";
  private static counter = 0;

  constructor(private readonly page: Page) {}

  static sign(body: string, secret = Provider.SECRET): string {
    return createHmac("sha256", secret).update(body).digest("hex");
  }

  /** `succeeded`, `failed`, `refunded` or `disputed` for `order`. */
  async say(kind: string, order: Order, over: { amount?: number; eventId?: string; secret?: string; currency?: string } = {}): Promise<Reply> {
    const body = JSON.stringify({
      id: over.eventId ?? `evt-${Date.now()}-${Provider.counter++}`,
      type: kind,
      provider_ref: `fake_${order.id}`,
      payment_ref: `pay_${order.id.slice(0, 8)}`,
      amount_paise: over.amount ?? order.amount_paise,
      currency: over.currency ?? "INR",
      occurred_at: new Date().toISOString(),
    });
    const response = await this.page.request.post("/api/payments/webhooks/fake", {
      data: Buffer.from(body),
      headers: { "Content-Type": "application/json", "X-Fake-Signature": Provider.sign(body, over.secret) },
    });
    return { status: response.status(), body: await response.json().catch(() => null) };
  }
}
