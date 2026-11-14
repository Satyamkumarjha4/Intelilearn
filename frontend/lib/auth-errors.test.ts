/**
 * Unit under test: `AuthErrors`, every error the sign-in screens can meet, in plain words.
 *
 * Why: a learner must never read a status, a code name or "ApiError", and the words for a wrong code must be the same
 * whatever was wrong with it (they say nothing about the address). The server's own sentence is kept for what it said that
 * is not listed here.
 *
 * Use cases:
 * - a wrong email or password, a wrong code, a sign-in that needs a code, too many tries (with and without a wait), no
 *   network and anything else each get plain words, and no message holds an internal word
 * - each code a refused sign-in with a provider can come back with has plain words of its own, an unknown one gets the
 *   general words, and no error means no card
 * - the waits read as seconds or minutes, singular and plural
 * - `needsCode` is true only for the `verification_required` error
 * - a missing or failed sign-up check (`captcha_failed`) says to complete the security check, in plain words
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { AuthErrors } from "./auth-errors";

const error = (status: number, code: string, message = "server words", retry: number | null = null) =>
  new ApiError(status, code, message, {}, {}, retry);

describe("message", () => {
  test("each known error has its words", () => {
    expect(AuthErrors.message(error(401, "invalid_credentials"))).toBe("That email and password don't match. Check them and try again.");
    expect(AuthErrors.message(error(400, "invalid_code"))).toBe(AuthErrors.INVALID_CODE);
    expect(AuthErrors.message(error(403, "verification_required"))).toBe("We sent you a code. Check your email to finish signing in.");
    expect(AuthErrors.message(error(429, "throttled", "x", 30))).toBe("Too many tries. Please wait 30 seconds and try again.");
    expect(AuthErrors.message(error(429, "throttled"))).toBe("Too many tries. Please wait a minute and try again.");
  });

  test("a missing or failed sign-up check says to complete the security check", () => {
    expect(AuthErrors.message(error(400, "captcha_failed"))).toBe("Please complete the security check and try again.");
    expect(AuthErrors.CAPTCHA_FAILED).not.toMatch(/captcha|turnstile|token/i);
  });

  test("no network, or something that is not an API error", () => {
    expect(AuthErrors.message(new TypeError("fetch failed"))).toBe("We couldn't reach Socra. Check your connection and try again.");
  });

  test("anything else the server said is kept", () => {
    expect(AuthErrors.message(error(400, "invalid", "Please correct the highlighted fields."))).toBe("Please correct the highlighted fields.");
  });

  test("no sentence holds a word a learner should not read", () => {
    const all = [error(401, "invalid_credentials"), error(400, "invalid_code"), error(403, "verification_required"), error(429, "throttled")];
    for (const e of all) expect(AuthErrors.message(e)).not.toMatch(/OTP|token|pending|canonical|ApiError|\b4\d\d\b/i);
  });
});

describe("callbackMessage", () => {
  test.each(["email_not_verified", "provider_off", "state_mismatch", "sign_in_failed", "account_closed"])("%s has its own words", (code) => {
    const words = AuthErrors.callbackMessage(code);

    expect(words).toBeString();
    expect(words).not.toMatch(/OTP|token|pending|verification|canonical|state|nonce|identity/i);
  });

  test("the five codes have five different sentences, and an unknown code gets the general one", () => {
    const codes = ["email_not_verified", "provider_off", "state_mismatch", "sign_in_failed", "account_closed"];

    expect(new Set(codes.map((code) => AuthErrors.callbackMessage(code))).size).toBe(5);
    expect(AuthErrors.callbackMessage("something_new")).toBe(AuthErrors.callbackMessage("sign_in_failed"));
  });

  test("no error, no card", () => {
    expect(AuthErrors.callbackMessage(null)).toBeNull();
    expect(AuthErrors.callbackMessage(undefined)).toBeNull();
    expect(AuthErrors.callbackMessage("")).toBeNull();
  });
});

describe("wait", () => {
  test.each([
    [null, "a minute"],
    [1, "1 second"],
    [45, "45 seconds"],
    [60, "1 minute"],
    [61, "2 minutes"],
    [600, "10 minutes"],
  ])("%p reads %p", (seconds, words) => {
    expect(AuthErrors.wait(seconds)).toBe(words);
  });
});

describe("needsCode", () => {
  test("only for verification_required", () => {
    expect(AuthErrors.needsCode(error(403, "verification_required"))).toBe(true);
    expect(AuthErrors.needsCode(error(403, "forbidden"))).toBe(false);
    expect(AuthErrors.needsCode(new Error("x"))).toBe(false);
  });
});
