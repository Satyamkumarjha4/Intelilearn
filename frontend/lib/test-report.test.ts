/**
 * Unit under test: `TestReport`, how a submitted test is told to the learner: the headline, the stat chips, each
 * question's status and the answers side by side, and the follow-up lesson on a topic.
 *
 * Why: this is what a learner takes away from the test. A headline that cheers a failing score (or scolds a good one),
 * a "correct answer" that leaks a marking scheme, an unanswered question shown as an empty line, or a follow-up lesson
 * request that is too long for the API would each make the page feel wrong or break it.
 *
 * Use cases:
 * - the headline is warm at every score and follows the band of the percent
 * - the stats count correct (full marks), partly right, missed and written answers graded by AI, and pending ones
 * - a question's status is right, partial, wrong or pending from its marks
 * - the learner's answer is shown as the option's text (multiple choice), the number with its unit, or their own words;
 *   a blank one says so
 * - the correct answer is the right option, the number (with unit), the model answer or the reference solution, and is
 *   missing when the marking scheme has none
 * - a follow-up lesson is asked for on a topic, naming the lesson, within the API's length limits
 * - a refused follow-up (too many lessons) is explained, and other failures fall back to a general message
 */
import { describe, expect, test } from "bun:test";

import { TestReport } from "./test-report";
import type { LearnerTestQuestion, QuestionResult } from "./types";

const row = (over: Partial<QuestionResult> = {}): QuestionResult => ({
  id: "t1", type: "mcq", concept: "Halving", marks: 4, awarded: 4, correct: true, graded_by: "auto", feedback: "", solution: {}, ...over,
});
const question = (over: Partial<LearnerTestQuestion> = {}): LearnerTestQuestion => ({ id: "t1", type: "mcq", question: "Q?", marks: 4, options: ["red", "green", "blue", "pink"], ...over });

describe("headline", () => {
  test.each([
    [100, "Outstanding"], [90, "Outstanding"], [89, "Great"], [75, "Great"], [60, "Solid"], [50, "Solid"], [30, "good start"], [25, "good start"], [10, "tough"], [0, "tough"],
  ])("%i%% says %s", (percent, word) => {
    expect(TestReport.headline(percent)).toContain(word);
  });
});

describe("stats", () => {
  test("count full marks, partly right, missed, AI graded and pending", () => {
    const rows = [
      row(), row({ id: "2" }), row({ id: "3", awarded: 2 }), row({ id: "4", awarded: 0, correct: false }),
      row({ id: "5", awarded: 4, graded_by: "model" }), row({ id: "6", awarded: null, graded_by: "none" }),
    ];

    expect(TestReport.stats(rows)).toEqual({ correct: 3, partial: 1, missed: 1, aiGraded: 1, pending: 1 });
  });

  test("an empty test has nothing to count", () => {
    expect(TestReport.stats([])).toEqual({ correct: 0, partial: 0, missed: 0, aiGraded: 0, pending: 0 });
  });
});

describe("status", () => {
  test.each([
    [{ awarded: 4 }, "right"], [{ awarded: 5 }, "right"], [{ awarded: 2 }, "partial"], [{ awarded: 0 }, "wrong"], [{ awarded: null }, "pending"],
  ] as const)("%j is %s", (over, status) => {
    expect(TestReport.status(row(over))).toBe(status);
  });
});

describe("the learner's answer", () => {
  test("a multiple choice answer is the option's text with its letter", () => {
    expect(TestReport.yourAnswer(question(), 2)).toEqual({ text: "C. blue" });
  });

  test("a number comes with its unit, and words stay as written", () => {
    expect(TestReport.yourAnswer(question({ type: "numerical", unit: "steps" }), "4")).toEqual({ text: "4 steps" });
    expect(TestReport.yourAnswer(question({ type: "numerical" }), "4")).toEqual({ text: "4" });
    expect(TestReport.yourAnswer(question({ type: "short_answer" }), "Halve it")).toEqual({ text: "Halve it" });
  });

  test("code is shown as code", () => {
    expect(TestReport.yourAnswer(question({ type: "code" }), "def f(): pass")).toEqual({ text: "def f(): pass", code: true });
  });

  test.each([[undefined], [null], [""], ["  "], [7]])("%p is no answer for a written question", (value) => {
    expect(TestReport.yourAnswer(question({ type: "short_answer" }), value)).toBeNull();
  });

  test("an option that does not exist is no answer", () => {
    expect(TestReport.yourAnswer(question(), 9)).toBeNull();
    expect(TestReport.yourAnswer(question(), "x")).toBeNull();
  });
});

describe("the correct answer", () => {
  test("is the right option, the number, the model answer or the reference solution", () => {
    expect(TestReport.correctAnswer(question(), { correct_index: 1 })).toEqual({ text: "B. green" });
    expect(TestReport.correctAnswer(question({ type: "numerical", unit: "steps" }), { answer: 4, unit: "steps" })).toEqual({ text: "4 steps" });
    expect(TestReport.correctAnswer(question({ type: "short_answer" }), { model_answer: "Halve the range." })).toEqual({ text: "Halve the range." });
    expect(TestReport.correctAnswer(question({ type: "code" }), { reference_solution: "return 1" })).toEqual({ text: "return 1", code: true });
  });

  test("is missing when the marking scheme has none", () => {
    expect(TestReport.correctAnswer(question(), {})).toBeNull();
    expect(TestReport.correctAnswer(question(), { correct_index: 9 })).toBeNull();
    expect(TestReport.correctAnswer(question({ type: "long_answer" }), { rubric: ["x"] })).toBeNull();
  });
});

describe("follow-up lesson", () => {
  test("asks for a lesson on the topic and names the lesson it follows", () => {
    expect(TestReport.followUp("Binary search", "Halving the range")).toEqual({
      topic: "Halving the range", context: "Follow-up to my Binary search test",
    });
  });

  test("keeps within the API's limits", () => {
    const made = TestReport.followUp("L".repeat(2000), "T".repeat(500));

    expect(made.topic).toHaveLength(200);
    expect(made.context.length).toBeLessThanOrEqual(1000);
  });

  test("a topic that is too short for the API is padded with the lesson's name", () => {
    expect(TestReport.followUp("Binary search", "x").topic.length).toBeGreaterThanOrEqual(2);
  });

  test("a refusal for too many lessons is explained, anything else is general", () => {
    expect(TestReport.followUpError(429)).toContain("a little while");
    expect(TestReport.followUpError(500)).toContain("couldn't start");
    expect(TestReport.followUpError(undefined)).toContain("couldn't start");
  });
});
