/**
 * Unit under test: `TestResultView`, how an attempt's result is told.
 *
 * Why: the score is what a learner takes from the test. A card that says "70%" while answers are still being graded
 * misleads them, and a question must say who marked it so a model's mark is never mistaken for a person's.
 *
 * Use cases:
 * - the summary says marks and percent, and "so far" while grading is incomplete
 * - each question is full, partial, none or pending, with a label that says so, and who marked it
 * - topics to revisit are listed
 */
import { describe, expect, test } from "bun:test";

import { TestResultView } from "./test-session";
import type { QuestionResult, ScoreCard } from "./types";

const row = (over: Partial<QuestionResult> = {}): QuestionResult => ({
  id: "t1", type: "mcq", concept: "Halving", marks: 4, awarded: 4, correct: true, graded_by: "auto", feedback: "Correct.", solution: {}, ...over,
});
const card = (over: Partial<ScoreCard> = {}): ScoreCard => ({
  complete: true, score: { awarded: 14, available: 20, percent: 70 }, questions: [row()], topics_to_revisit: ["Halving", "Cost"], ...over,
});

describe("TestResultView", () => {
  test("summarises marks and percent, and says when it is not final", () => {
    expect(TestResultView.summary(card())).toBe("14 of 20 marks (70%)");
    expect(TestResultView.summary(card({ complete: false }))).toBe("14 of 20 marks (70%) so far");
  });

  test.each([
    [{ awarded: 4 }, "full", "Full marks"],
    [{ awarded: 2 }, "partial", "2 of 4 marks"],
    [{ awarded: 0 }, "none", "0 of 4 marks"],
    [{ awarded: null, correct: null, graded_by: "none" as const }, "pending", "Being graded"],
  ])("a question with %p is %s", (over, tone, label) => {
    const result = row(over);

    expect([TestResultView.tone(result), TestResultView.label(result)]).toEqual([tone, label]);
  });

  test("says who marked a question", () => {
    expect(TestResultView.source(row({ graded_by: "auto" }))).toBe("Marked automatically");
    expect(TestResultView.source(row({ graded_by: "model" }))).toBe("Graded by AI");
    expect(TestResultView.source(row({ graded_by: "none" }))).toBe("");
  });

  test("lists the topics to revisit", () => {
    expect(TestResultView.topics(card())).toBe("Halving, Cost");
    expect(TestResultView.topics(card({ topics_to_revisit: [] }))).toBe("");
  });
});
