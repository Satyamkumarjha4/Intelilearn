/**
 * Unit under test: `TestimonialForm`, the console's testimonial form (lib/console-testimonials).
 *
 * Why: a testimonial is shown to every visitor under a real person's name, so the form must stop what the server and the
 * database would stop anyway, early and in words: a blank field, a quote that is too long, a rating that is not 1 to 5, and
 * above all publishing without the learner's consent or publishing a sample. An edit sends only what changed, and moving a
 * row never loses or repeats an id (the reorder endpoint needs every id exactly once).
 *
 * Use cases:
 * - a blank form has nothing set and is not valid; a complete one is valid
 * - a blank name, context or quote, a name or context over 80 characters and a quote over 300 each name their field
 * - the rating is empty (none) or 1 to 5; anything else is a problem
 * - it cannot be published without consent, or if it is a sample, and the reason is given; with consent it can
 * - the payload trims the text and turns an empty rating into none
 * - an edit sends only the fields that differ from the saved row
 * - moving a row up or down swaps it with its neighbour, and at either end changes nothing or an unknown id
 * - the quote counter reads "n / 300"
 */
import { describe, expect, test } from "bun:test";

import { TestimonialForm } from "./testimonial-form";
import type { ConsoleTestimonial } from "./types";

const row: ConsoleTestimonial = {
  id: 1, name: "Asha Rao", context: "Class 12 student", quote: "It skipped what I knew.", rating: 5, position: 1,
  is_published: false, consent_confirmed: false, is_sample: false, created_at: "2026-11-10T10:00:00Z", updated_at: "2026-11-10T10:00:00Z",
}; // fmt: skip
const good = TestimonialForm.from(row);

describe("problems", () => {
  test("a blank form is not valid, a complete one is", () => {
    expect(Object.keys(TestimonialForm.problems(TestimonialForm.blank())).sort()).toEqual(["context", "name", "quote"]);
    expect(TestimonialForm.problems(good)).toEqual({});
  });

  test.each([
    [{ name: "   " }, "name"],
    [{ name: "n".repeat(81) }, "name"],
    [{ context: "" }, "context"],
    [{ context: "c".repeat(81) }, "context"],
    [{ quote: " " }, "quote"],
    [{ quote: "q".repeat(301) }, "quote"],
  ])("%p names the field %s", (change, field) => {
    expect(Object.keys(TestimonialForm.problems({ ...good, ...change }))).toEqual([field]);
  });

  test("a quote of exactly 300 characters is fine", () => {
    expect(TestimonialForm.problems({ ...good, quote: "q".repeat(300) })).toEqual({});
  });

  test.each([["", null], ["3", 3], [" 5 ", 5], ["0", undefined], ["6", undefined], ["4.5", undefined], ["x", undefined]])("a rating of %p reads %p", (text, expected) => {
    expect(TestimonialForm.rating(text)).toBe(expected);
  });

  test("a bad rating is a problem on the rating", () => {
    expect(Object.keys(TestimonialForm.problems({ ...good, rating: "9" }))).toEqual(["rating"]);
  });
});

describe("publishing", () => {
  test("without consent it cannot be published, and says why", () => {
    expect(TestimonialForm.cannotPublish(good, false)).toMatch(/agreed to be quoted/);
    expect(TestimonialForm.problems({ ...good, is_published: true }).is_published).toMatch(/agreed to be quoted/);
  });

  test("a sample can never be published, with or without consent", () => {
    const consenting = { ...good, consent_confirmed: true, is_published: true };

    expect(TestimonialForm.cannotPublish(consenting, true)).toMatch(/sample/i);
    expect(TestimonialForm.problems(consenting, true).is_published).toMatch(/sample/i);
  });

  test("with consent and no sample flag it can be published", () => {
    const publish = { ...good, consent_confirmed: true, is_published: true };

    expect(TestimonialForm.cannotPublish(publish, false)).toBeNull();
    expect(TestimonialForm.problems(publish)).toEqual({});
  });
});

describe("what is sent", () => {
  test("the payload trims the text and makes an empty rating none", () => {
    expect(TestimonialForm.payload({ ...good, name: "  Asha  ", rating: "" })).toEqual({
      name: "Asha", context: "Class 12 student", quote: "It skipped what I knew.", rating: null, consent_confirmed: false, is_published: false,
    }); // fmt: skip
  });

  test("an edit sends only what differs from the saved row", () => {
    expect(TestimonialForm.changes(row, good)).toEqual({});
    expect(TestimonialForm.changes(row, { ...good, quote: "New words.", consent_confirmed: true })).toEqual({ quote: "New words.", consent_confirmed: true });
    expect(TestimonialForm.changes(row, { ...good, rating: "" })).toEqual({ rating: null });
  });
});

describe("moving a row", () => {
  test("a row swaps with its neighbour", () => {
    expect(TestimonialForm.move([1, 2, 3], 2, -1)).toEqual([2, 1, 3]);
    expect(TestimonialForm.move([1, 2, 3], 2, 1)).toEqual([1, 3, 2]);
  });

  test("at either end, or for an unknown id, nothing changes", () => {
    expect(TestimonialForm.move([1, 2, 3], 1, -1)).toEqual([1, 2, 3]);
    expect(TestimonialForm.move([1, 2, 3], 3, 1)).toEqual([1, 2, 3]);
    expect(TestimonialForm.move([1, 2, 3], 9, 1)).toEqual([1, 2, 3]);
  });

  test("the original list is not changed", () => {
    const ids = [1, 2, 3];

    TestimonialForm.move(ids, 2, -1);

    expect(ids).toEqual([1, 2, 3]);
  });
});

test("the quote counter reads n / 300", () => {
  expect(TestimonialForm.count(" hello ")).toBe("5 / 300");
});
