/**
 * Unit under test: `QuizNames`, what a learner calls each of the two checks.
 *
 * Why: the API says "diagnostic" and "prerequisite", which are not words a student uses. The same two names must appear
 * in the answers tab, the "done" card and the screen-reader label of a score, or the lesson seems to talk about three
 * different things.
 *
 * Use cases:
 * - the first check is the "Quick check" and the second is the "Foundations check"
 * - the done card says which one is done
 * - nothing a learner reads contains the API's own words
 */
import { describe, expect, test } from "bun:test";

import { QuizNames } from "./quiz-names";

describe("QuizNames", () => {
  test("names the two checks the way learners do", () => {
    expect(QuizNames.of("diagnostic")).toBe("Quick check");
    expect(QuizNames.of("prerequisite")).toBe("Foundations check");
  });

  test("says which check is done", () => {
    expect(QuizNames.done("diagnostic")).toBe("Quick check done!");
    expect(QuizNames.done("prerequisite")).toBe("Foundations check done!");
  });

  test("a score's label for a screen reader never says diagnostic or prerequisite", () => {
    for (const kind of ["diagnostic", "prerequisite"] as const) {
      expect(QuizNames.resultLabel(kind)).toMatch(/result$/);
      expect(QuizNames.resultLabel(kind)).not.toMatch(/diagnostic|prerequisite|quiz/i);
    }
  });
});
