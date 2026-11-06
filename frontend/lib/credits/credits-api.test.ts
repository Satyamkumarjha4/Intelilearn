/**
 * Unit under test: `CreditsApi`, the typed calls to the credits endpoints.
 *
 * Why: every credits screen goes through it, so a wrong path or a missing encoding breaks them all at once. API paths
 * have no trailing slash (the Next.js proxy depends on it), and a cursor or a lesson id is a value to encode, not to trust.
 *
 * Use cases:
 * - each call goes to its path with the right method and body
 * - the history sends the cursor only when there is one, encoded
 * - a retry quote sends the lesson id, encoded
 */
import { describe, expect, test } from "bun:test";

import type { ApiClient } from "@/lib/api";

import { CreditsApi } from "./credits-api";

function recorder() {
  const calls: { path: string; options?: { method?: string; body?: unknown } }[] = [];
  const client = { request: async (path: string, options?: { method?: string; body?: unknown }) => (calls.push({ path, options }), {}) } as unknown as ApiClient;
  return { calls, api: new CreditsApi(client) };
}

describe("the calls", () => {
  test("each goes to its path, without a trailing slash", async () => {
    const { api, calls } = recorder();

    await api.wallet();
    await api.balance();
    await api.notices();
    await api.streak();
    await api.plans();

    expect(calls.map((c) => c.path)).toEqual(["/credits/wallet", "/credits/balance", "/credits/notices", "/credits/streak", "/credits/plans"]);
  });

  test("a quote and a repair are posts", async () => {
    const { api, calls } = recorder();

    await api.quote("lesson.create", { entry: "diagnostic" });
    await api.repair();

    expect(calls).toEqual([
      { path: "/credits/quote", options: { method: "POST", body: { action: "lesson.create", size: { entry: "diagnostic" } } } },
      { path: "/credits/streak/repair", options: { method: "POST" } },
    ]);
  });
});

describe("encoding", () => {
  test("the history sends the cursor only when there is one, encoded", async () => {
    const { api, calls } = recorder();

    await api.transactions();
    await api.transactions(null);
    await api.transactions("a b&c=");

    expect(calls.map((c) => c.path)).toEqual(["/credits/transactions", "/credits/transactions", "/credits/transactions?cursor=a%20b%26c%3D"]);
  });

  test("a retry quote sends the lesson id, encoded", async () => {
    const { api, calls } = recorder();

    await api.retryQuote("a/b");

    expect(calls[0].path).toBe("/credits/retry-quote?lesson=a%2Fb");
  });
});
