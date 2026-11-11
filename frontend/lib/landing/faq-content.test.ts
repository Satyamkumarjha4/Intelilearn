/**
 * Unit under test: `FaqContent`, the eight questions of the landing page's FAQ.
 *
 * Why: an answer that quotes a number must quote the one the server gives, or the page and the checkout would disagree;
 * and when the numbers could not be read, the answer must still read well without them. The privacy answer links to the
 * policy and names no payment method. The tests assert the numbers and the structure, never the sentences, so the words
 * can be improved without touching them.
 *
 * Use cases:
 * - there are eight questions, each distinct, each a question, each with an answer
 * - the answers quote the sign-up credits, the lessons they make, the prices, the Quick check length and how long credits
 *   last from the numbers given, so changing a number changes the answer
 * - a missing price leaves out just that number
 * - with no pricing at all every answer is still text and contains no digit
 * - the privacy answer links to the Privacy Policy and never names a payment method
 */
import { describe, expect, test } from "bun:test";

import { FaqContent, type FaqItem } from "./faq-content";
import { pricing } from "./fixtures";

const plain = (item: FaqItem) => item.answer.map((part) => (typeof part === "string" ? part : part.text)).join("");
/** Every whole number the answers say, as a set: what the page quotes, whatever the words around it. */
const numbers = (p = pricing()) => new Set(FaqContent.items(p).flatMap((item) => [...plain(item).matchAll(/\d+/g)].map((m) => Number(m[0]))));

// Numbers no other field of the fixture uses, so each one found in an answer can only have come from its own field.
const DISTINCT = { signup_credits: 47, signup_about_lessons: 6, lesson_credits: 13, retake_credits: 7, bonus_valid_days: 61, quick_check_questions: 17 };

describe("the questions", () => {
  test("there are eight, each distinct, each a question, each with an answer", () => {
    const items = FaqContent.items(pricing());

    expect(items).toHaveLength(8);
    expect(new Set(items.map((i) => i.question)).size).toBe(8);
    for (const item of items) {
      expect(item.question.endsWith("?")).toBe(true);
      expect(plain(item).trim().length).toBeGreaterThan(0);
    }
  });
});

describe("numbers come from the server", () => {
  test("the answers quote what they were given", () => {
    const quoted = numbers(pricing(DISTINCT));

    for (const value of Object.values(DISTINCT)) expect(quoted.has(value)).toBe(true);
  });

  test("the seeded prices are quoted as they are", () => {
    const quoted = numbers();

    for (const value of [30, 3, 10, 2, 90]) expect(quoted.has(value)).toBe(true);
  });

  test("a changed number changes the answer and the old one is gone", () => {
    const before = numbers(pricing({ signup_credits: 30 }));
    const after = numbers(pricing({ signup_credits: 47 }));

    expect(before.has(30) && !before.has(47)).toBe(true);
    expect(after.has(47) && !after.has(30)).toBe(true);
  });

  test("a missing price leaves out only that number", () => {
    const full = numbers(pricing(DISTINCT));
    const without = numbers(pricing({ ...DISTINCT, retake_credits: null }));

    expect(full.has(7) && !without.has(7)).toBe(true);
    expect([...full].filter((n) => n !== 7).every((n) => without.has(n))).toBe(true);
  });

  test("with no pricing at all every answer is text and holds no digit", () => {
    for (const item of FaqContent.items(null)) {
      expect(plain(item).trim().length).toBeGreaterThan(0);
      expect(plain(item)).not.toMatch(/\d/);
    }
  });
});

describe("privacy", () => {
  test("it links to the policy and names no payment method", () => {
    const item = FaqContent.items(pricing()).at(-1)!;

    expect(item.answer.some((part) => typeof part !== "string" && part.href === "/privacy")).toBe(true);
    expect(plain(item)).not.toMatch(/upi|visa|mastercard|paypal|netbanking|rupay/i);
  });
});
