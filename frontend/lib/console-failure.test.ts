/**
 * Unit under test: `ConsoleFailure`, which turns a failed console request into words and per-field messages.
 *
 * Why: the console's forms (routing, settings, models, providers) all save through the same API, whose refusals are a
 * `400` with messages per field, a `409` with a reason, a `404` for something that is gone, or a throttle. Each form
 * showing the raw API text, or none, would leave the staff guessing what to fix.
 *
 * Use cases:
 * - a 400 carries the API's messages per field, and the general line
 * - the field messages can be listed as lines, with a readable name for each field
 * - a 409 gives its reason; a 404 says the thing is gone; a throttled request says when to try again
 * - anything else (a network failure, a 500) gets one calm sentence
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { ConsoleFailure } from "./console-failure";

describe("of", () => {
  test("a 400 keeps the messages per field", () => {
    const failure = ConsoleFailure.of(new ApiError(400, "invalid", "Please correct the highlighted fields.", { timeout_s: ["Too small."], bindings: ["Model 1 (a/b): no key."] }));

    expect(failure.fields).toEqual({ timeout_s: ["Too small."], bindings: ["Model 1 (a/b): no key."] });
    expect(failure.message).toBe("Please correct the highlighted fields.");
  });

  test("a 409 gives its reason", () => {
    expect(ConsoleFailure.of(new ApiError(409, "model_in_use", "Used by lesson.plan.")).message).toBe("Used by lesson.plan.");
  });

  test("a 404 says the thing is gone", () => {
    expect(ConsoleFailure.of(new ApiError(404, "not_found", "Not found.")).message).toContain("not there any more");
  });

  test("a throttled request says when to try again", () => {
    const failure = ConsoleFailure.of(new ApiError(429, "throttled", "Slow down", {}, {}, 12));

    expect(failure.message).toContain("12 seconds");
    expect(ConsoleFailure.of(new ApiError(429, "throttled", "Slow down")).message).toContain("a moment");
  });

  test("a network failure or anything unknown gets one calm sentence and no fields", () => {
    for (const error of [new TypeError("fetch failed"), "boom", null]) {
      const failure = ConsoleFailure.of(error);

      expect(failure.message).toBe("That did not work. Check the connection and try again.");
      expect(failure.fields).toEqual({});
    }
  });

  test("a server error keeps the API's sentence", () => {
    expect(ConsoleFailure.of(new ApiError(500, "error", "Something broke.")).message).toBe("Something broke.");
  });
});

describe("lines", () => {
  test("lists each field message under the field's readable name, and bare messages for a field without one", () => {
    const failure = ConsoleFailure.of(new ApiError(400, "invalid", "x", { timeout_s: ["Too small."], bindings: ["Model 1: no key.", "Model 2: off."], other: ["Odd."] }));

    expect(failure.lines({ timeout_s: "Timeout" })).toEqual(["Timeout: Too small.", "Model 1: no key.", "Model 2: off.", "Odd."]);
  });

  test("with no field messages, it is the one sentence", () => {
    expect(ConsoleFailure.of(new ApiError(409, "x", "Nope.")).lines({})).toEqual(["Nope."]);
  });
});
