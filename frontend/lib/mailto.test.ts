/**
 * Unit under test: `Mailto`, the links that open the learner's mail app with a subject (and a message) filled in.
 *
 * Why: a subject with a bracket, a slash or an ampersand, or a message with line breaks and a lesson link full of `?`
 * and `&`, must arrive whole. A badly encoded link opens an email with a cut-off subject or a broken body.
 *
 * Use cases:
 * - the link has the address, the subject, and the message only when there is one
 * - spaces are %20 (a "+" would show as a plus in many mail apps), and brackets, slashes, ampersands, line breaks and
 *   non-English letters are encoded so they come out unchanged
 */
import { describe, expect, test } from "bun:test";

import { Mailto } from "./mailto";

describe("link", () => {
  test("has the address and the subject, and a message only when there is one", () => {
    expect(Mailto.link("a@b.co", "[Socra] Feedback")).toBe("mailto:a@b.co?subject=%5BSocra%5D%20Feedback");
    expect(Mailto.link("a@b.co", "Hi", "Hello")).toBe("mailto:a@b.co?subject=Hi&body=Hello");
  });

  test("encodes what would otherwise break the link, and it decodes back to the same text", () => {
    const body = "Lesson: https://socra.example/lessons/1?tab=lesson&x=1\nPage: 2 / 3 · हिन्दी\n";
    const link = Mailto.link("a@b.co", "[Socra] Parent / teacher", body);
    const params = new URLSearchParams(link.split("?")[1]);

    expect(params.get("subject")).toBe("[Socra] Parent / teacher");
    expect(params.get("body")).toBe(body);
    expect(link).not.toContain("+");
    expect(link).not.toContain(" ");
    expect(link).not.toContain("\n");
  });
});
