/**
 * Unit under test: `CaptchaRules` (`lib/captcha.ts`), the rules of the sign-up check apart from its widget.
 *
 * Why: the check is off until staff switch it on, and a form that wrongly waits for a token that never comes would lock
 * every new person out, while one that wrongly skips it would leave the check useless.
 *
 * Use cases:
 * - the server's answer is read as a config; anything unreadable, or "on" without a key, is treated as off
 * - with the check off a form can always be sent; with it on, only with a token
 * - the token is added to a request body only when there is one, and the body is not changed otherwise
 */
import { describe, expect, test } from "bun:test";

import { CaptchaRules } from "./captcha";

describe("CaptchaRules.parse", () => {
  test("reads the on state with its key", () => {
    expect(CaptchaRules.parse({ enabled: true, site_key: "abc" })).toEqual({ enabled: true, site_key: "abc" });
  });

  test.each([[null], ["on"], [{}], [{ enabled: false, site_key: "" }], [{ enabled: true, site_key: "" }], [{ enabled: "true", site_key: "abc" }], [{ enabled: true }]])(
    "%p is off",
    (value) => {
      expect(CaptchaRules.parse(value)).toEqual({ enabled: false, site_key: "" });
    },
  );
});

describe("CaptchaRules.canSend", () => {
  const on = { enabled: true, site_key: "abc" };

  test("a form can always be sent while the check is off", () => {
    expect(CaptchaRules.canSend(CaptchaRules.OFF, null)).toBe(true);
  });

  test("with the check on it needs a token", () => {
    expect(CaptchaRules.canSend(on, null)).toBe(false);
    expect(CaptchaRules.canSend(on, "")).toBe(false);
    expect(CaptchaRules.canSend(on, "token")).toBe(true);
  });
});

describe("CaptchaRules.withToken", () => {
  test("adds the token when there is one", () => {
    expect(CaptchaRules.withToken({ email: "a@b.c" }, "t")).toEqual({ email: "a@b.c", captcha_token: "t" });
  });

  test("leaves the body as it is without one", () => {
    const body = { email: "a@b.c" };
    expect(CaptchaRules.withToken(body, null)).toBe(body);
  });
});
