/**
 * Unit under test: `AdjustForm` (giving or taking credits), `RefundForm` (the rupees of a refund) and `EraseForm`
 * (deleting a learner's data) of the console.
 *
 * Why: these forms move credits and money. The reason for a hand-made credit change is required (it is the only record
 * of why a balance moved), the amount must be a real whole number, and the refund box must never turn a typo into a
 * different amount than the person meant: it is rupees to the paisa or empty.
 *
 * Use cases:
 * - AdjustForm: an amount is a whole number other than zero, with an optional sign; anything else is null
 * - the reason is required (blank and spaces refused) and limited; both problems are reported together
 * - the button says what it will do, with the right singular and plural, and says nothing specific for a bad amount
 * - RefundForm: empty means all that remains; rupees with up to two decimals are accepted; zero, negative, three
 *   decimals, letters and commas are refused
 * - the refund body has the token always and the amount only when one was typed
 * - EraseForm: the email typed matches the account's in any case with spaces ignored and nothing else; a blank account
 *   email never matches; each reason an account cannot be erased reads in words; what was taken reads as one line
 */
import { describe, expect, test } from "bun:test";

import { AdjustForm, EraseForm, RefundForm } from "./forms";

describe("AdjustForm", () => {
  test.each([["25", 25], ["+25", 25], ["-4", -4], [" 7 ", 7]])("%j is %i credits", (text, number) => {
    expect(AdjustForm.amount(text)).toBe(number);
  });

  test.each(["", "0", "-0", "1.5", "ten", "1 000", "--3", "12345678"])("%j is not an amount", (text) => {
    expect(AdjustForm.amount(text)).toBeNull();
  });

  test("the reason is required and limited, and both problems come together", () => {
    expect(AdjustForm.errors("5", "A goodwill gift")).toEqual({});
    expect(AdjustForm.errors("5", "   ").reason).toBe("Say why the credits are being given or taken.");
    expect(AdjustForm.errors("5", "x".repeat(501)).reason).toBe("At most 500 characters.");
    expect(Object.keys(AdjustForm.errors("0", ""))).toEqual(["amount", "reason"]);
  });

  test("the button says what it will do", () => {
    expect(AdjustForm.summary("1")).toBe("Give 1 credit");
    expect(AdjustForm.summary("25")).toBe("Give 25 credits");
    expect(AdjustForm.summary("-1")).toBe("Take 1 credit");
    expect(AdjustForm.summary("-4")).toBe("Take 4 credits");
    expect(AdjustForm.summary("x")).toBe("Give or take credits");
  });
});

describe("RefundForm", () => {
  test("empty means all that remains", () => {
    expect(RefundForm.amount("")).toEqual({ ok: true, rupees: "" });
    expect(RefundForm.amount("  ")).toEqual({ ok: true, rupees: "" });
  });

  test.each(["40", "12.5", "12.50", " 0.01 "])("%j is an amount", (text) => {
    expect(RefundForm.amount(text)).toEqual({ ok: true, rupees: text.trim() });
  });

  test.each(["0", "0.00", "-5", "1.234", "ten", "1,000", "₹5", "."])("%j is refused", (text) => {
    const result = RefundForm.amount(text);

    expect(result.ok).toBe(false);
    expect(result.ok === false && result.error).toContain("rupees");
  });

  test("the body has the token, and the amount only when one was typed", () => {
    expect(RefundForm.body("t1", "")).toEqual({ token: "t1" });
    expect(RefundForm.body("t1", "12.50")).toEqual({ token: "t1", amount: "12.50" });
  });
});

describe("EraseForm", () => {
  test.each([["ada@example.com", true], ["ADA@Example.com", true], ["  ada@example.com ", true], ["ada@example.co", false], ["ada", false], ["", false], ["xada@example.com", false]])(
    "%j against ada@example.com is %p",
    (typed, matches) => {
      expect(EraseForm.matches(typed, "ada@example.com")).toBe(matches);
    },
  );

  test("an account with no email never matches, even an empty box", () => {
    expect(EraseForm.matches("", "")).toBe(false);
    expect(EraseForm.matches("  ", "  ")).toBe(false);
  });

  test("every reason it is blocked has words, and allowed has none", () => {
    expect(EraseForm.blocked("cannot_erase_self")).toContain("your own account");
    expect(EraseForm.blocked("staff_account")).toContain("Django admin");
    expect(EraseForm.blocked("already_erased")).toContain("already been erased");
    expect(EraseForm.blocked("")).toBe("");
  });

  test("what was taken reads as one line, with singular and plural", () => {
    expect(EraseForm.done({ lessons: 2, quizzes: 1, credits_forfeited: 80, refresh_tokens: 1 })).toBe("Erased: 2 lessons, 1 quiz, 80 credits written off, sign-ins ended.");
    expect(EraseForm.done({ lessons: 1, quizzes: 3, credits_forfeited: 1, refresh_tokens: 0 })).toBe("Erased: 1 lesson, 3 quizzes, 1 credit written off, sign-ins ended.");
  });
});
