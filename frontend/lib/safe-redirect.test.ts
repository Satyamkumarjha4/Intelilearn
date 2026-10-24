import { describe, expect, test } from "bun:test";

import { safeNext } from "./safe-redirect";

describe("safeNext", () => {
  test.each([
    ["/profile", "/profile"],
    ["/lessons/123?tab=quiz#q2", "/lessons/123?tab=quiz#q2"],
    ["/", "/"],
  ])("keeps same-site path %p", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
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
    expect(safeNext(input)).toBe("/");
  });

  test("rejects non-strings", () => {
    expect(safeNext(undefined)).toBe("/");
    expect(safeNext(["/profile"])).toBe("/");
  });
});
