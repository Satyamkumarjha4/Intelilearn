/**
 * Unit under test: `FaqContent`, the eight questions of the landing page's FAQ.
 *
 * Why: an answer that quotes a number must quote the one the server gives, or the page and the checkout would disagree;
 * and when the numbers could not be read, the answer must still read well without them. The privacy answer says payment
 * details stay with the payment provider and names no payment method.
 *
 * Use cases:
 * - there are eight questions, in order
 * - the answers quote the sign-up credits, the lessons they make, the prices, the Quick check length and how long credits
 *   last from the numbers given, so changing a number changes the answer
 * - with no pricing at all every answer is still a sentence and contains no digit
 * - a missing price leaves just that part out of "how do credits work"
 * - the privacy answer links to the Privacy Policy, says payment details stay with the provider, and never names UPI
 */
import { describe, expect, test } from "bun:test";

import { FaqContent, type FaqItem } from "./faq-content";
import { pricing } from "./fixtures";

const plain = (item: FaqItem) => item.answer.map((part) => (typeof part === "string" ? part : part.text)).join("");
const answers = (p = pricing()) => Object.fromEntries(FaqContent.items(p).map((item) => [item.question, plain(item)]));

describe("the questions", () => {
  test("there are eight, in order", () => {
    expect(FaqContent.items(pricing()).map((i) => i.question)).toEqual([
      "How does Socra know my level?",
      "How do credits work?",
      "Is it free to start?",
      "Do credits expire?",
      "Will I be charged automatically?",
      "What if a lesson fails to build?",
      "Who is Socra for?",
      "Is my data private?",
    ]);
  });
});

describe("numbers come from the server", () => {
  test("the answers quote what they were given", () => {
    const a = answers();

    expect(a["How does Socra know my level?"]).toContain("10-question Quick check");
    expect(a["How do credits work?"]).toContain("A full lesson with its Test is 10, a retake is 2, a sheet is 2 to 3 and a quick quiz is 1 to 4.");
    expect(a["Is it free to start?"]).toBe("Yes. You get 30 credits when you sign up, enough for about 3 full lessons, with no card needed.");
    expect(a["Do credits expire?"]).toContain("Your 30 sign-up credits never do. Credits you earn last 90 days, credits you buy last a year,");
  });

  test("a changed number changes the answer", () => {
    const a = answers(pricing({ signup_credits: 50, signup_about_lessons: 5, lesson_credits: 12, bonus_valid_days: 60, quick_check_questions: 15 }));

    expect(a["Is it free to start?"]).toContain("50 credits");
    expect(a["Is it free to start?"]).toContain("about 5 full lessons");
    expect(a["How do credits work?"]).toContain("A full lesson with its Test is 12");
    expect(a["Do credits expire?"]).toContain("last 60 days");
    expect(a["How does Socra know my level?"]).toContain("15-question Quick check");
  });

  test("a missing price leaves out only that part", () => {
    const text = answers(pricing({ retake_credits: null }))["How do credits work?"];

    expect(text).toContain("A full lesson with its Test is 10, a sheet is 2 to 3 and a quick quiz is 1 to 4.");
    expect(text).not.toContain("retake");
  });

  test("with no pricing at all every answer still reads and holds no digit", () => {
    for (const item of FaqContent.items(null)) {
      expect(plain(item).length).toBeGreaterThan(10);
      expect(plain(item)).not.toMatch(/\d/);
    }
  });
});

describe("privacy", () => {
  test("it links to the policy, says payment details stay with the provider and names no method", () => {
    const item = FaqContent.items(pricing()).at(-1)!;

    expect(item.answer.some((part) => typeof part !== "string" && part.href === "/privacy" && part.text === "Privacy Policy")).toBe(true);
    expect(plain(item)).toContain("payment details stay with the payment provider");
    expect(plain(item)).not.toMatch(/upi/i);
  });
});
