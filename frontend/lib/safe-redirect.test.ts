/**
 * Unit under test: `RedirectPolicy.safeNext`, which decides where `/auth?next=…` may send a user after sign-in.
 *
 * Why: an open redirect after sign-in lets a phishing link bounce a freshly signed-in user to an attacker's site.
 *
 * Use cases:
 * - keeps same-site paths, including query and hash
 * - rejects protocol-relative, backslash, tab-smuggled, absolute, scheme and bare-host values
 * - rejects non-string input (missing or repeated query parameter)
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
