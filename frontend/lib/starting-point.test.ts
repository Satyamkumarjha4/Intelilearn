/**
 * Unit under test: `StartingPoint`, which turns the assessment and the quick check result into what the "Your starting
 * point" card shows.
 *
 * Why: the card is the learner's first picture of themselves in the lesson, built from model output (a level word, a
 * confidence word) and a score per band. An unexpected word must not break the card, and an "I don't know" must not be
 * shown as a plain wrong answer when the review tells them apart.
 *
 * Use cases:
 * - the level maps to a meter of four segments with a label; an unknown level fills nothing and keeps its own word
 * - each band shows one dot per question: right answers first, then wrong ones, from the score alone
 * - with the review, a dot is right, wrong or "I don't know" for each question of the band
 * - bands come easiest first and bands that were not asked are left out
 * - the confidence maps to a fraction of the bar with a label; an unknown word is a third of the bar
 * - a learner who rated themselves gets their stars and their own sentence, no quiz bands and no confidence bar, because
 *   nothing was tested; the level is still the level the stars mean
 * - known concepts, gaps and the start point are passed on
 */
import { describe, expect, test } from "bun:test";

import { StartingPoint } from "./starting-point";
import type { Assessment, QuizResultSummary, ReviewQuestion } from "./types";

const assessment = (over: Partial<Assessment> = {}): Assessment => ({
  level: "beginner", known_concepts: ["loops"], gaps: ["recursion"], start_point: "Start with arrays", confidence: "medium", ...over,
});
const result = (over: Partial<QuizResultSummary> = {}): QuizResultSummary => ({
  correct: 5, total: 8, dont_know: 1, by_band: { hard: [0, 2], basic: [2, 2], moderate: [1, 2] }, ...over,
});
const review = (rows: [string, ReviewQuestion["answer"], boolean][]) => ({
  questions: rows.map(([band, answer, correct], n) => ({
    id: `q${n}`, band, question: "", options: [], correct_index: 0, explanation: "", answer, correct,
  })) as ReviewQuestion[],
});

describe("level meter", () => {
  test.each([
    ["beginner", 1, "New to it"],
    ["foundation", 2, "Finding your feet"],
    ["proficient", 3, "Getting comfortable"],
    ["expert", 4, "Expert"],
    ["Foundation ", 2, "Finding your feet"],
  ])("%s fills %i of 4 segments and reads %s", (level, filled, label) => {
    expect(StartingPoint.of(assessment({ level }), result()).level).toEqual({ filled, total: 4, label });
  });

  test("an unknown level fills nothing and keeps its own word", () => {
    expect(StartingPoint.of(assessment({ level: "wizard" }), result()).level).toEqual({ filled: 0, total: 4, label: "Wizard" });
  });
});

describe("bands", () => {
  test("from the score alone, right answers come first and the rest are wrong", () => {
    const bands = StartingPoint.of(assessment(), result()).bands;

    expect(bands.map((b) => [b.band, b.label, b.dots])).toEqual([
      ["basic", "Basics", ["right", "right"]],
      ["moderate", "Standard problems", ["right", "wrong"]],
      ["hard", "Expert", ["wrong", "wrong"]],
    ]);
  });

  test("with the review, a dot says right, wrong or I don't know for each question of the band", () => {
    const rows = review([
      ["basic", 0, true], ["basic", 1, false], ["moderate", "dont_know", false], ["moderate", 0, true], ["hard", "dont_know", false],
    ]);

    const bands = StartingPoint.of(assessment(), result(), rows).bands;

    expect(bands.map((b) => [b.band, b.dots])).toEqual([
      ["basic", ["right", "wrong"]],
      ["moderate", ["unsure", "right"]],
      ["hard", ["unsure"]],
    ]);
  });

  test("a review without bands falls back to the score", () => {
    const bands = StartingPoint.of(assessment(), result({ by_band: { basic: [1, 2] } }), review([["", 0, true]])).bands;

    expect(bands.map((b) => b.dots)).toEqual([["right", "wrong"]]);
  });

  test("without a result there are no bands", () => {
    expect(StartingPoint.of(assessment(), null).bands).toEqual([]);
  });
});

describe("confidence", () => {
  test.each([
    ["low", 1 / 3, "Still getting to know you"],
    ["medium", 2 / 3, "Fairly sure"],
    ["high", 1, "Very sure"],
    ["???", 1 / 3, "Still getting to know you"],
  ])("%s", (confidence, fraction, label) => {
    expect(StartingPoint.of(assessment({ confidence }), result()).confidence).toEqual({ fraction, label });
  });
});

test("known concepts, gaps and where the lesson begins are passed on", () => {
  const view = StartingPoint.of(assessment(), result());

  expect([view.known, view.gaps, view.startPoint]).toEqual([["loops"], ["recursion"], "Start with arrays"]);
});

describe("a learner who rated themselves", () => {
  const rated = (stars: number | null = 3.5, over: Partial<Assessment> = {}) =>
    StartingPoint.of(assessment({ source: "self_rating", level: "foundation", known_concepts: [], gaps: [], confidence: "low", ...over }), null, null, stars);

  test("their stars and the sentence they picked are shown, with the level the stars mean", () => {
    const view = rated(3.5);

    expect(view.rating).toEqual({ halves: 7, label: "3.5 stars", sentence: "I can solve most simple problems and I am starting on harder ones." });
    expect(view.level.label).toBe("Finding your feet");
    expect(view.bands).toEqual([]);
  });

  test("there is no confidence bar, because nothing was tested", () => {
    expect(rated().confidence).toBeNull();
  });

  test("the assessment alone says it was a rating, even before the stars arrive", () => {
    const view = rated(null);

    expect(view.rating).toBeNull();
    expect(view.confidence).toBeNull();
  });

  test("the stars alone are enough, for an assessment from before it said where it came from", () => {
    expect(StartingPoint.of(assessment(), null, null, 2).confidence).toBeNull();
  });

  test("a rating that is not on the scale is ignored", () => {
    expect(rated(2.3, { source: "diagnostic" }).rating).toBeNull();
    expect(rated(2.3, { source: "diagnostic" }).confidence).not.toBeNull();
  });

  test("a quick check keeps its bands, its confidence and no rating", () => {
    const view = StartingPoint.of(assessment({ source: "diagnostic" }), result(), null, null);

    expect(view.rating).toBeNull();
    expect(view.confidence).toEqual({ fraction: 2 / 3, label: "Fairly sure" });
    expect(view.bands.length).toBeGreaterThan(0);
  });
});
