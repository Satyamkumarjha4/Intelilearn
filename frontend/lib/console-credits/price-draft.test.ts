/**
 * Unit under test: `PriceForm`, the price table being edited in the console.
 *
 * Why: a price decides what every learner pays for an action, and an edit adds a row to its history. The form must only
 * send rows that were edited, refuse a price that is not a whole number of credits (0 is a price), and keep the quote
 * line's words from going blank, so nobody changes a price by a slip of the keyboard.
 *
 * Use cases:
 * - the draft starts as each key's live price and words; a key with no live price starts empty
 * - dirty names the edited keys only; an edit to the words alone counts
 * - the errors: not a whole number, empty, negative; empty or over-long words; rows that were not edited are not judged
 * - the changes: one per edited row, with the words only when they changed; an unusable price is not sent
 */
import { describe, expect, test } from "bun:test";

import { PriceForm } from "./price-draft";
import type { ConsolePrice } from "./types";

const price = (key: string, credits: number | null, label = key): ConsolePrice => ({
  key,
  label,
  credits,
  available: credits !== null,
  updated_by: "",
  updated_at: "2026-11-07T00:00:00Z",
  history: [],
});
const prices = [price("lesson.full", 10, "Your lesson"), price("test.retake", 2, "Retake"), price("old.key", null, "Old")];

describe("PriceForm", () => {
  test("starts as the live prices and words, and a key with no price starts empty", () => {
    expect(PriceForm.from(prices)).toEqual({
      "lesson.full": { credits: "10", label: "Your lesson" },
      "test.retake": { credits: "2", label: "Retake" },
      "old.key": { credits: "", label: "Old" },
    });
    expect(PriceForm.dirty(prices, PriceForm.from(prices))).toEqual([]);
  });

  test("dirty names only the edited keys, and the words alone count", () => {
    const draft = PriceForm.from(prices);
    draft["lesson.full"].credits = "12";
    draft["test.retake"].label = "Test again";

    expect(PriceForm.dirty(prices, draft)).toEqual(["lesson.full", "test.retake"]);
  });

  test.each(["", "-1", "1.5", "free", "1 0"])("a price of %j is refused", (credits) => {
    const draft = PriceForm.from(prices);
    draft["lesson.full"].credits = credits;

    expect(PriceForm.errors(prices, draft)["lesson.full"].credits).toBe("Enter a whole number of credits (0 is allowed).");
  });

  test("zero is a price", () => {
    const draft = PriceForm.from(prices);
    draft["lesson.full"].credits = "0";

    expect(PriceForm.errors(prices, draft)).toEqual({});
  });

  test("the words must say something and fit", () => {
    const draft = PriceForm.from(prices);
    draft["lesson.full"].label = "  ";
    draft["test.retake"].label = "x".repeat(121);

    const errors = PriceForm.errors(prices, draft);

    expect(errors["lesson.full"].label).toBe("Say what this line is called.");
    expect(errors["test.retake"].label).toBe("At most 120 characters.");
  });

  test("a row that was not edited is not judged, even if it has no price", () => {
    expect(PriceForm.errors(prices, PriceForm.from(prices))).toEqual({});
  });

  test("giving a key with no price one is an edit", () => {
    const draft = PriceForm.from(prices);
    draft["old.key"].credits = "3";

    expect(PriceForm.changes(prices, draft)).toEqual([{ key: "old.key", body: { credits: 3 } }]);
  });

  test("the changes are one per edited row, with the words only when they changed, and an unusable price is not sent", () => {
    const draft = PriceForm.from(prices);
    draft["lesson.full"].credits = " 12 ";
    draft["test.retake"].label = "Test again";
    draft["old.key"].credits = "x";

    expect(PriceForm.changes(prices, draft)).toEqual([
      { key: "lesson.full", body: { credits: 12 } },
      { key: "test.retake", body: { credits: 2, label: "Test again" } },
    ]);
  });
});
