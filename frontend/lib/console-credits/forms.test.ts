/**
 * Unit under test: `AdjustForm` (giving or taking credits) and `RefundForm` (the rupees of a refund) of the console.
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
 */
import { describe, expect, test } from "bun:test";

import { AdjustForm, RefundForm } from "./forms";

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
