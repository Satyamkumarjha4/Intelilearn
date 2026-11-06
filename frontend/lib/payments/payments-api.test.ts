/**
 * Unit under test: `PaymentsApi`, the typed calls to the payments endpoints.
 *
 * Why: starting a payment must carry its idempotency key (a double click is one order), must never carry a price, and an
 * order id in a path is a value to encode. Paths have no trailing slash.
 *
 * Use cases:
 * - the gateways and the orders are read from their paths, and the list is unwrapped
 * - starting a payment posts the plan, the quantity or the credits and the gateway, with the Idempotency-Key header
 * - one order is read by its encoded id
 */
import { expect, test } from "bun:test";

import type { ApiClient } from "@/lib/api";

import { PaymentsApi } from "./payments-api";

function recorder(answer: unknown = {}) {
  const calls: { path: string; options?: { method?: string; body?: unknown; headers?: Record<string, string> } }[] = [];
  const client = { request: async (path: string, options?: object) => (calls.push({ path, options }), answer) } as unknown as ApiClient;
  return { calls, api: new PaymentsApi(client) };
}

test("the gateways and the orders are read from their paths and the list is unwrapped", async () => {
  const { api, calls } = recorder({ orders: [{ id: "a" }] });

  await api.gateways();
  const orders = await api.orders();

  expect(calls.map((c) => c.path)).toEqual(["/payments/gateways", "/payments/orders"]);
  expect(orders).toEqual([{ id: "a" }] as never);
});

test("starting a payment posts what to buy with the idempotency key and no price", async () => {
  const { api, calls } = recorder();

  await api.createOrder({ plan: "one_time", credits: 100, gateway: "stripe" }, "key-1");

  expect(calls[0]).toEqual({
    path: "/payments/orders",
    options: { method: "POST", body: { plan: "one_time", credits: 100, gateway: "stripe" }, headers: { "Idempotency-Key": "key-1" } },
  });
});

test("one order is read by its encoded id", async () => {
  const { api, calls } = recorder();

  await api.order("a/b");

  expect(calls[0].path).toBe("/payments/orders/a%2Fb");
});
