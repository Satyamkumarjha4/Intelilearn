import { apiClient, type ApiClient } from "@/lib/api";

import type { BuyRequest, CreatedOrder, Gateways, Order } from "./types";

/** The payments endpoints, typed. */
export class PaymentsApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  gateways(): Promise<Gateways> {
    return this.client.request("/payments/gateways");
  }

  /** Starts a payment. The key makes a double click (or a retry after a dropped answer) the same order. */
  createOrder(request: BuyRequest, idempotencyKey: string): Promise<CreatedOrder> {
    return this.client.request("/payments/orders", { method: "POST", body: request, headers: { "Idempotency-Key": idempotencyKey } });
  }

  order(id: string): Promise<Order> {
    return this.client.request(`/payments/orders/${encodeURIComponent(id)}`);
  }

  async orders(): Promise<Order[]> {
    return (await this.client.request<{ orders: Order[] }>("/payments/orders")).orders;
  }
}

export const paymentsApi = new PaymentsApi();
