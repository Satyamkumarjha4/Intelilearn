/**
 * Unit under test: `RedirectPolicy.safeNext`, which decides where `/auth?next=…` may send a user after sign-in.
 *
 * Why: an open redirect after sign-in lets a phishing link bounce a freshly signed-in user to an attacker's site.
 *
 * Use cases:
 * - keeps same-site paths, including query and hash
 * - rejects protocol-relative, backslash, tab-smuggled, absolute, scheme and bare-host values
 * - percent-encoded look-alikes (%2F, %5C, %09) and values that only become dangerous when decoded again stay inside the
 *   site: they come out as same-site paths, or are refused, and never as another host
 * - rejects non-string input (missing or repeated query parameter)
 * - answers with the fallback given (the app's home is /lessons) whenever the value is refused
 */
import { describe, expect, test } from "bun:test";

import { RedirectPolicy } from "./safe-redirect";

describe("RedirectPolicy.safeNext", () => {
  test.each([
    ["/profile", "/profile"],
    ["/lessons/123?tab=quiz#q2", "/lessons/123?tab=quiz#q2"],
    ["/", "/"],
  ])("keeps same-site path %p", (input, expected) => {
    expect(RedirectPolicy.safeNext(input)).toBe(expected);
  });

  test.each([
    "//evil.com",
    "/\\evil.com", // browsers read a backslash as a slash
    "/\\/evil.com",
    "/\t/evil.com", // tab is stripped by the URL parser
    "https://evil.com",
    "javascript:alert(1)",
    "evil.com",
    "",
  ])("rejects %p", (input) => {
    expect(RedirectPolicy.safeNext(input)).toBe("/");
  });

  test("rejects non-strings", () => {
    expect(RedirectPolicy.safeNext(undefined)).toBe("/");
    expect(RedirectPolicy.safeNext(["/profile"])).toBe("/");
  });
});

describe("RedirectPolicy.safeNext fallback", () => {
  test.each([
    [undefined, "/lessons"],
    ["https://evil.example", "/lessons"],
    ["//evil.example", "/lessons"],
    ["/lessons/abc?tab=test", "/lessons/abc?tab=test"],
  ])("%p goes to %s when the fallback is /lessons", (input, expected) => {
    expect(RedirectPolicy.safeNext(input, "/lessons")).toBe(expected);
  });
});

describe("RedirectPolicy.safeNext with encoded input", () => {
  test.each(["/%2F%2Fevil.com", "/%5Cevil.com", "/%09/evil.com", "/%2f/evil.com", "/%252F%252Fevil.com", "/..%2F..%2Fevil.com"])(
    "%p never leaves the site",
    (input) => {
      const result = RedirectPolicy.safeNext(input, "/fallback");

      expect(result.startsWith("/")).toBe(true);
      expect(result.startsWith("//")).toBe(false);
      expect(new URL(result, "http://app.test").origin).toBe("http://app.test");
    },
  );

  test.each(["%2F%2Fevil.com", "%2Fevil.com", "https%3A%2F%2Fevil.com"])("%p, which is not a path at all, is refused", (input) => {
    expect(RedirectPolicy.safeNext(input, "/fallback")).toBe("/fallback");
  });

  test("a value that decodes to a protocol-relative address is refused once the caller has decoded it", () => {
    expect(RedirectPolicy.safeNext(decodeURIComponent("%2F%2Fevil.com"), "/fallback")).toBe("/fallback");
  });
});
