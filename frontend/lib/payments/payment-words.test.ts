/**
 * Unit under test: `PaymentWords`, what a payment says to a learner.
 *
 * Why: a payment that does not start, or is still being confirmed, is a worrying moment, so the words must be calm, say
 * whether anything was charged, and never show a status code, a state name or a provider's word.
 *
 * Use cases:
 * - each way a payment can be refused has its own sentence; one the server wrote for a person is kept; anything else is a
 *   plain "nothing was charged, try again"; being rate limited says to wait
 * - the headline and detail follow what the page knows: confirming, still confirming, done, failed or timed out
 * - a finished order says how many credits were added (singular and plural), and a plan says it has started
 * - no word of the machinery appears in any of them
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "@/lib/api";

import { PaymentWords } from "./payment-words";
import type { Order } from "./types";

const refused = (status: number, code: string, message = "") => new ApiError(status, code, message);
const order = (over: Partial<Order> = {}): Order => ({
  id: "o1", status: "fulfilled", gateway: "fake", plan: { key: "one_time", name: "One-time credits" }, quantity: 1, credits: 100,
  amount_paise: 10000, currency: "INR", refunded_paise: 0, created_at: "2026-11-07T10:00:00Z", fulfilled_at: null, ...over,
});

describe("a payment that could not start", () => {
  test.each([
    ["too_many_pending", 409, "still being confirmed"],
    ["queue_full", 409, "as many plans lined up"],
    ["gateway_unavailable", 502, "Nothing was charged"],
    ["gateway_not_enabled", 400, "isn't available"],
  ])("%s has its own sentence", (code, status, text) => {
    expect(PaymentWords.refusal(refused(status, code))).toContain(text);
  });

  test("an amount or a plan the server wrote a message for keeps its message", () => {
    expect(PaymentWords.refusal(refused(400, "invalid_amount", "The smallest amount is 10 credits."))).toBe("The smallest amount is 10 credits.");
    expect(PaymentWords.refusal(refused(400, "invalid_plan", ""))).toContain("can't be bought");
  });

  test("anything else says nothing was charged, and a rate limit says to wait", () => {
    expect(PaymentWords.refusal(new Error("boom"))).toBe(PaymentWords.TRY_AGAIN);
    expect(PaymentWords.refusal(refused(500, "error"))).toBe(PaymentWords.TRY_AGAIN);
    expect(PaymentWords.refusal(refused(429, "throttled"))).toContain("Wait a moment");
  });
});

describe("the page after paying", () => {
  test("the headline follows the phase", () => {
    expect(PaymentWords.headline(null, "waiting")).toBe("Confirming your payment");
    expect(PaymentWords.headline(null, "slow")).toBe("Still confirming your payment");
    expect(PaymentWords.headline(order(), "done")).toBe("Your credits are here");
    expect(PaymentWords.headline(order({ status: "failed" }), "failed")).toBe("That payment didn't go through");
    expect(PaymentWords.headline(order({ status: "expired" }), "failed")).toBe("That payment timed out");
  });

  test("the detail says what was added, and calms a slow or failed payment", () => {
    expect(PaymentWords.detail(order(), "done", false)).toBe("100 credits were added.");
    expect(PaymentWords.detail(order({ credits: 1 }), "done", false)).toBe("1 credit was added.");
    expect(PaymentWords.detail(order({ plan: { key: "weekly_pro", name: "Weekly Pro" }, credits: 200 }), "done", false)).toBe(
      "Weekly Pro has started. Its credits come a period at a time, and the first ones are in your wallet now.",
    );
    expect(PaymentWords.detail(null, "slow", false)).toContain("You can leave this page");
    expect(PaymentWords.detail(null, "failed", false)).toContain("Nothing was charged");
  });

  test("coming back without paying is treated gently", () => {
    expect(PaymentWords.detail(null, "waiting", true)).toContain("changed your mind");
    expect(PaymentWords.detail(null, "waiting", false)).toContain("a few seconds");
  });

  test("no word of the machinery reaches a learner", () => {
    const text = [
      PaymentWords.TRY_AGAIN,
      ...["too_many_pending", "queue_full", "gateway_unavailable", "gateway_not_enabled"].map((c) => PaymentWords.refusal(refused(400, c))),
      ...(["waiting", "slow", "done", "failed"] as const).flatMap((p) => [PaymentWords.headline(order(), p), PaymentWords.detail(order(), p, true)]),
    ].join(" ");

    expect(text).not.toMatch(/\b(webhook|gateway|ledger|bucket|hold|order state|fulfil|reconcil|status code)\b/i);
  });
});
