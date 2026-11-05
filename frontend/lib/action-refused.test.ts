/**
 * Unit under test: `ActionRefusedMessage`, the one place that turns a refused action into words for the learner.
 *
 * Why: screens that start paid work will one day be told "no" by a pricing feature. If each screen read that in its own
 * way, one would show a raw status code, another would call a sign-in problem a refusal, and a third would lose the
 * reason the server took the trouble to write.
 *
 * Use cases:
 * - a 403 that is not about the person is a refusal, and its own message is what the learner reads
 * - a refusal without a message falls back to a plain sentence
 * - a 403 for "not allowed" or "not signed in", any other status, and anything that is not an API error are not refusals
 * - the words never name a status code or the machinery
 * - a 402 `insufficient_credits` is a refusal too; its message is kept, or built from what it needs and what there is,
 *   and it comes with the path to buy more; no other 402 is a refusal, and a 403 refusal comes with no buy path
 * - `refusal` gives the message, the buy path and the two numbers in one object, or null for anything else
 */
import { describe, expect, test } from "bun:test";

import { ActionRefusedMessage } from "./action-refused";
import { ApiError } from "./api";

const error = (status: number, code: string, message: string, extra: Record<string, unknown> = {}) => new ApiError(status, code, message, {}, extra);

describe("a refusal", () => {
  test.each(["action_refused", "out_of_credits", "test_refused"])("a 403 with code %s is one, and its message is kept", (code) => {
    const refusal = error(403, code, "You have used all your lessons for today.");

    expect(ActionRefusedMessage.isRefusal(refusal)).toBe(true);
    expect(ActionRefusedMessage.of(refusal)).toBe("You have used all your lessons for today.");
  });

  test("without a message it falls back to a plain sentence", () => {
    expect(ActionRefusedMessage.of(error(403, "action_refused", "  "))).toBe(ActionRefusedMessage.FALLBACK);
  });

  test("the fallback names no status code or machinery", () => {
    expect(ActionRefusedMessage.FALLBACK).not.toMatch(/\b4\d\d\b|credit|gate|queue|llm|model/i);
  });
});

describe("not enough credits (402)", () => {
  const poor = (message = "You need 10 credits for this and have 4.", extra: Record<string, unknown> = { required: 10, available: 4 }) =>
    error(402, "insufficient_credits", message, extra);

  test("it is a refusal and its own message is what the learner reads", () => {
    expect(ActionRefusedMessage.isRefusal(poor())).toBe(true);
    expect(ActionRefusedMessage.of(poor())).toBe("You need 10 credits for this and have 4.");
  });

  test("without a message the words are built from the two numbers", () => {
    expect(ActionRefusedMessage.of(poor("  "))).toBe("You need 10 credits for that and have 4.");
  });

  test("without a message or numbers it falls back to a plain sentence", () => {
    expect(ActionRefusedMessage.of(poor("", {}))).toBe(ActionRefusedMessage.INSUFFICIENT_FALLBACK);
    expect(ActionRefusedMessage.of(poor("", { required: "ten", available: null }))).toBe(ActionRefusedMessage.INSUFFICIENT_FALLBACK);
  });

  test("one credit is not 'credits'", () => {
    expect(ActionRefusedMessage.of(poor("", { required: 1, available: 0 }))).toBe("You need 1 credit for that and have 0.");
  });

  test("the refusal carries the path to buy more and the numbers", () => {
    expect(ActionRefusedMessage.refusal(poor())).toEqual({
      message: "You need 10 credits for this and have 4.",
      buyPath: "/buy",
      required: 10,
      available: 4,
    });
    expect(ActionRefusedMessage.BUY_PATH).toBe("/buy");
  });

  test("numbers that are not whole numbers are left out", () => {
    expect(ActionRefusedMessage.refusal(poor("Not enough.", { required: "ten", available: 1.5 }))).toEqual({
      message: "Not enough.",
      buyPath: "/buy",
      required: null,
      available: null,
    });
  });

  test("a 402 with another code is not a refusal", () => {
    expect(ActionRefusedMessage.isRefusal(error(402, "payment_required", "x"))).toBe(false);
    expect(ActionRefusedMessage.refusal(error(402, "payment_required", "x"))).toBeNull();
  });

  test("a 403 refusal has no buy path", () => {
    expect(ActionRefusedMessage.refusal(error(403, "action_refused", "Not today."))).toEqual({
      message: "Not today.",
      buyPath: null,
      required: null,
      available: null,
    });
  });

  test("anything else has no refusal", () => {
    expect(ActionRefusedMessage.refusal(new Error("boom"))).toBeNull();
    expect(ActionRefusedMessage.refusal(error(404, "not_found", "x"))).toBeNull();
  });
});

describe("not a refusal", () => {
  test.each([
    error(403, "permission_denied", "You do not have permission to perform this action."),
    error(403, "not_authenticated", "Authentication credentials were not provided."),
    error(401, "not_authenticated", "x"),
    error(400, "invalid", "x"),
    error(404, "not_found", "x"),
    error(409, "wrong_stage", "x"),
    error(429, "throttled", "x"),
    error(503, "llm_not_configured", "x"),
    new Error("boom"),
    "text",
    undefined,
    null,
  ])("%p", (value) => {
    expect(ActionRefusedMessage.isRefusal(value)).toBe(false);
    expect(ActionRefusedMessage.of(value)).toBeNull();
  });
});
