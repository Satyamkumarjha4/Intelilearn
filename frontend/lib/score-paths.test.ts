/**
 * Unit under test: `ScorePaths`, which path a quick-check score leads to, and the landing page's three slides.
 *
 * Why: the landing page promises "your score decides what happens next". The slides must say the same thing the
 * product does (0–2 foundations, 3–9 a lesson, 10 a study sheet), with no score left out or in two places, and each
 * example learner's score must land on the slide that shows it.
 *
 * Use cases:
 * - every score from 0 to 10 leads to exactly one path, at the edges 2/3 and 9/10
 * - a score outside 0–10, or not a whole number, leads nowhere
 * - the ten dots of a score: that many filled, the rest empty
 * - the slides cover 0–10 without a gap or an overlap, in order
 * - each slide's example learner scores within the slide's own range
 */
import { describe, expect, test } from "bun:test";

import { PATH_SLIDES, type PathId } from "./landing-content";
import { ScorePaths } from "./score-paths";

describe("ScorePaths", () => {
  test.each<[number, PathId]>([
    [0, "foundations"],
    [2, "foundations"],
    [3, "lesson"],
    [9, "lesson"],
    [10, "mastery"],
  ])("a score of %i leads to %s", (score, path) => {
    expect(ScorePaths.pathFor(score)).toBe(path);
  });

  test.each([[-1], [11], [2.5], [NaN]])("a score of %p leads nowhere", (score) => {
    expect(ScorePaths.pathFor(score)).toBeNull();
  });

  test("the dots of a score are that many filled, then empty", () => {
    expect(ScorePaths.dots(7)).toEqual([...Array(7).fill(true), ...Array(3).fill(false)]);
    expect(ScorePaths.dots(0).some(Boolean)).toBe(false);
    expect(ScorePaths.dots(10).every(Boolean)).toBe(true);
  });

  test("the slides cover every score once, in order", () => {
    const seen = PATH_SLIDES.flatMap((slide) => Array.from({ length: slide.scores[1] - slide.scores[0] + 1 }, (_, n) => slide.scores[0] + n));

    expect(seen).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  test("each slide's example learner scores within the slide's own range", () => {
    for (const slide of PATH_SLIDES) expect(ScorePaths.pathFor(slide.example.score)).toBe(slide.id);
  });
});
