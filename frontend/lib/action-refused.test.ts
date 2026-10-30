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
 */
import { describe, expect, test } from "bun:test";

import { ActionRefusedMessage } from "./action-refused";
import { ApiError } from "./api";

const error = (status: number, code: string, message: string) => new ApiError(status, code, message);

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
