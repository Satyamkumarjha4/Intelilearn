/**
 * Unit under test: the `headers` option of `ApiClient.request`.
 *
 * Why: starting a payment sends an `Idempotency-Key`, which only a request header can carry. It must be sent as given, and it
 * must not displace the headers the client always sets.
 *
 * Use cases:
 * - an extra header is sent with the request
 * - the content type and the CSRF header are still sent alongside it
 * - without the option nothing extra is sent
 */
import { expect, test } from "bun:test";

import { ApiClient } from "./api";

function run(options: Parameters<ApiClient["request"]>[1]) {
  const seen: Record<string, string>[] = [];
  const client = new ApiClient(async (_url, init) => {
    seen.push(init?.headers as Record<string, string>);
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  }, () => "csrf-token");
  return client.request("/payments/orders", options).then(() => seen[0]);
}

test("an extra header is sent with the request", async () => {
  expect((await run({ method: "POST", body: {}, headers: { "Idempotency-Key": "k-1" } }))["Idempotency-Key"]).toBe("k-1");
});

test("the content type and the CSRF header are still sent", async () => {
  const headers = await run({ method: "POST", body: { a: 1 }, headers: { "Idempotency-Key": "k-1" } });

  expect(headers["Content-Type"]).toBe("application/json");
  expect(headers["X-CSRFToken"]).toBe("csrf-token");
  expect(headers.Accept).toBe("application/json");
});

test("without the option nothing extra is sent", async () => {
  expect(Object.keys(await run({ method: "POST", body: {} })).sort()).toEqual(["Accept", "Content-Type", "X-CSRFToken"]);
});
