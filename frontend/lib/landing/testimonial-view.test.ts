/**
 * Unit under test: `TestimonialView`, how a published testimonial is laid out on the landing page.
 *
 * Why: the page must never show a star the learner did not give. Stars appear only when there is a rating, as many as
 * the rating says, with a label a screen reader can read; the round avatar is the learner's initials (there are no
 * photos), whatever punctuation the name carries.
 *
 * Use cases:
 * - initials are the first letters of the first two words, in capitals, ignoring brackets and punctuation; a name with
 *   no letters is "?"
 * - a rating of 1 to 5 gives five flags with that many filled and the label "N out of 5 stars"
 * - no rating, or one that is not 1 to 5, gives no stars and no label
 * - the avatar tone cycles through the three brand tones in order
 * - a card carries the name, context and quote as given
 */
import { describe, expect, test } from "bun:test";

import { TestimonialView } from "./testimonial-view";

describe("initials", () => {
  test.each([
    ["Asha Rao", "AR"],
    ["[Learner name]", "LN"],
    ["asha", "A"],
    ["Mary Jane Watson", "MJ"],
    ["  Åsa  Öberg ", "ÅÖ"],
    ["(( ))", "?"],
    ["", "?"],
  ])("%p gives %p", (name, initials) => {
    expect(TestimonialView.initials(name)).toBe(initials);
  });
});

describe("stars", () => {
  test("a rating fills that many of five and has a label", () => {
    expect(TestimonialView.stars(3)).toEqual([true, true, true, false, false]);
    expect(TestimonialView.ratingLabel(3)).toBe("3 out of 5 stars");
    expect(TestimonialView.stars(5)).toEqual([true, true, true, true, true]);
  });

  test.each([null, 0, 6, -1, 2.5])("a rating of %p shows no stars and no label", (rating) => {
    expect(TestimonialView.stars(rating)).toEqual([]);
    expect(TestimonialView.ratingLabel(rating)).toBeNull();
  });
});

describe("cards", () => {
  const rows = [
    { name: "Asha Rao", context: "Class 12 student", quote: "It skipped what I knew.", rating: 5 },
    { name: "Ben", context: "B.Tech", quote: "New questions each time.", rating: null },
    { name: "Chen Li", context: "Class 10", quote: "The sheet.", rating: 4 },
    { name: "Dev", context: "Class 9", quote: "Good.", rating: null },
  ];

  test("a card carries what the learner said, with initials, stars and a tone", () => {
    const [first, second] = TestimonialView.cards(rows);

    expect(first).toMatchObject({ name: "Asha Rao", context: "Class 12 student", quote: "It skipped what I knew.", initials: "AR", ratingLabel: "5 out of 5 stars" });
    expect(second.stars).toEqual([]);
  });

  test("the tone cycles through the three brand tones", () => {
    expect(TestimonialView.cards(rows).map((c) => c.tone)).toEqual(["primary", "marigold", "insight", "primary"]);
  });
});
