/**
 * Unit under test: `FieldDraft`, an edit in progress over a saved record of numbers, switches and words (the console's
 * plan and credit-settings forms).
 *
 * Why: a number being typed is not a number yet, so the boxes hold text, and the form still has to say what changed, what
 * is wrong, and send only what changed, as the right types. A wrong patch would change a price or a rule nobody meant to.
 *
 * Use cases:
 * - a draft starts as the saved values (numbers as text), and nothing is dirty
 * - dirty names the fields that differ, in the saved order, ignoring spaces around a number
 * - a number box that is empty, has a sign, a point, letters or spaces inside is "Enter a whole number."; words and
 *   switches are not judged
 * - the patch holds only what changed, numbers as numbers, a box that is not a number yet left out
 */
import { describe, expect, test } from "bun:test";

import { FieldDraft } from "./field-draft";

const saved = { name: "Weekly Pro", credits: 100, period_days: 7, active: true };

describe("FieldDraft", () => {
  test("starts as the saved values, with numbers as text, and is clean", () => {
    const draft = FieldDraft.from(saved);

    expect(draft).toEqual({ name: "Weekly Pro", credits: "100", period_days: "7", active: true });
    expect(FieldDraft.dirty(saved, draft)).toEqual([]);
    expect(FieldDraft.patch(saved, draft)).toEqual({});
  });

  test("dirty lists what differs in the saved order, and spaces around a number do not count", () => {
    const draft = { ...FieldDraft.from(saved), active: false, credits: " 100 ", name: "Pro" };

    expect(FieldDraft.dirty(saved, draft)).toEqual(["name", "active"]);
  });

  test.each(["", " ", "-1", "1.5", "ten", "1 0", "+5", "1234567890"])("%j is not a whole number", (text) => {
    const draft = { ...FieldDraft.from(saved), credits: text };

    expect(FieldDraft.errors(saved, draft)).toEqual({ credits: "Enter a whole number." });
  });

  test("zero is a whole number and words and switches are not judged", () => {
    const draft = { ...FieldDraft.from(saved), credits: "0", name: "", active: false };

    expect(FieldDraft.errors(saved, draft)).toEqual({});
  });

  test("the patch has only what changed, as numbers, words and switches", () => {
    const draft = { ...FieldDraft.from(saved), credits: "120", name: "Pro Week", active: false };

    expect(FieldDraft.patch(saved, draft)).toEqual({ name: "Pro Week", credits: 120, active: false });
  });

  test("a number box that is not a number yet is not sent", () => {
    const draft = { ...FieldDraft.from(saved), credits: "12x", period_days: "14" };

    expect(FieldDraft.dirty(saved, draft)).toEqual(["credits", "period_days"]);
    expect(FieldDraft.patch(saved, draft)).toEqual({ period_days: 14 });
  });

  test("a field the draft does not have is left alone", () => {
    expect(FieldDraft.dirty(saved, { credits: "1" })).toEqual(["credits"]);
  });
});
