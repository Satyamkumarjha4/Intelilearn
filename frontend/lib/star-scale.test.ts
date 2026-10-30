/**
 * Unit under test: `StarScale`, the ten half-star values of the self-rating, the sentence each one shows, and the keys
 * that move along them.
 *
 * Why: a learner who rates themselves skips the quick check, so this one pick decides where their lesson starts. A
 * sentence attached to the wrong value would tell them something they did not choose; a keyboard that cannot reach
 * every half star would shut some learners out of the form; a float instead of whole halves would drift in the API.
 *
 * Use cases:
 * - there are exactly ten steps, from half a star to five, in order, each with a distinct approved sentence (the first
 *   and last are pinned word for word) and a label that reads singular for one star
 * - a step is found by its halves, and anything that is not a whole number from 1 to 10 has none
 * - the sentence for no pick is empty, and before a pick the scale asks for one
 * - stars and halves convert both ways, and a value off the scale (2.3, 0, 5.5, NaN) has no halves
 * - every half star means the level in the spec (0.5–1.5 Beginner, 2–3.5 Foundation, 4 Proficient, 4.5–5 Expert)
 * - the arrow keys move a half star at a time and stop at both ends; Home and End jump to them; with nothing picked the
 *   first arrow picks an end; other keys are not handled
 * - a pick fills the half stars up to it
 */
import { describe, expect, test } from "bun:test";

import { StarScale } from "./star-scale";

describe("the steps", () => {
  test("ten values from half a star to five, in order", () => {
    expect(StarScale.all().map((s) => s.halves)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(StarScale.all().map((s) => s.stars)).toEqual([0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]);
  });

  test("the sentences are the approved ones, all different, the first and last word for word", () => {
    const sentences = StarScale.all().map((s) => s.sentence);

    expect(new Set(sentences).size).toBe(10);
    expect(sentences[0]).toBe("This is completely new to me.");
    expect(sentences[1]).toBe("I've heard the name, but I don't know what it means.");
    expect(sentences[9]).toBe("I could explain it to someone else.");
    expect(sentences.every((text) => text.trim().length > 0 && text.endsWith("."))).toBe(true);
  });

  test("the label says stars, and one star is singular", () => {
    expect(StarScale.of(1)?.label).toBe("0.5 stars");
    expect(StarScale.of(2)?.label).toBe("1 star");
    expect(StarScale.of(5)?.label).toBe("2.5 stars");
    expect(StarScale.of(10)?.label).toBe("5 stars");
  });
});

describe("finding a step", () => {
  test.each([1, 5, 10])("%d is on the scale", (halves) => {
    expect(StarScale.of(halves)?.halves).toBe(halves);
  });

  test.each([0, 11, -1, 2.5, Number.NaN, null, undefined])("%p is not", (value) => {
    expect(StarScale.of(value)).toBeNull();
  });

  test("before a pick the scale asks for one", () => {
    expect(StarScale.PROMPT).toBe("Pick the stars that fit you best.");
  });

  test("the sentence of a pick, and none before one is made", () => {
    expect(StarScale.sentence(6)).toBe("I know the basics and can solve simple problems.");
    expect(StarScale.sentence(null)).toBe("");
    expect(StarScale.sentence(0)).toBe("");
  });
});

describe("stars and halves", () => {
  test.each([[1, 0.5], [2, 1], [7, 3.5], [10, 5]])("%d halves is %d stars and back", (halves, stars) => {
    expect(StarScale.starsOf(halves)).toBe(stars);
    expect(StarScale.halvesOf(stars)).toBe(halves);
  });

  test.each([2.3, 0, 5.5, 0.25, Number.NaN, Number.POSITIVE_INFINITY, null, undefined])("%p stars is not on the scale", (stars) => {
    expect(StarScale.halvesOf(stars)).toBeNull();
  });
});

describe("the level a rating means", () => {
  test.each([
    [1, "beginner"], [2, "beginner"], [3, "beginner"], [4, "foundation"], [5, "foundation"], [6, "foundation"],
    [7, "foundation"], [8, "proficient"], [9, "expert"], [10, "expert"],
  ] as const)("%d halves is %s", (halves, level) => {
    expect(StarScale.levelOf(halves)).toBe(level);
  });

  test("a value off the scale has no level", () => {
    expect(StarScale.levelOf(0)).toBeNull();
    expect(StarScale.levelOf(null)).toBeNull();
  });
});

describe("moving with the keyboard", () => {
  test.each([["ArrowRight", 5, 6], ["ArrowUp", 5, 6], ["ArrowLeft", 5, 4], ["ArrowDown", 5, 4]])("%s from %d goes to %d", (key, from, to) => {
    expect(StarScale.move(from, key)).toBe(to);
  });

  test("it stops at both ends", () => {
    expect(StarScale.move(10, "ArrowRight")).toBe(10);
    expect(StarScale.move(1, "ArrowLeft")).toBe(1);
  });

  test("Home and End jump to the ends", () => {
    expect(StarScale.move(6, "Home")).toBe(1);
    expect(StarScale.move(6, "End")).toBe(10);
  });

  test("with nothing picked, the first arrow picks an end", () => {
    expect(StarScale.move(null, "ArrowRight")).toBe(1);
    expect(StarScale.move(null, "ArrowUp")).toBe(1);
    expect(StarScale.move(null, "ArrowLeft")).toBe(10);
  });

  test.each(["Tab", "Enter", " ", "a", "Escape"])("%j is not handled", (key) => {
    expect(StarScale.move(5, key)).toBeNull();
  });
});

describe("filling the row", () => {
  test("a pick fills the half stars up to it, and nothing fills nothing", () => {
    expect([1, 2, 3, 4, 5].map((slot) => StarScale.fills(3, slot))).toEqual([true, true, true, false, false]);
    expect(StarScale.fills(null, 1)).toBe(false);
  });
});
