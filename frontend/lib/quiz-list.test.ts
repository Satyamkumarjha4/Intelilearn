/**
 * Unit under test: `QuizList`, how a quick quiz reads in the learner's list.
 *
 * Why: the list is where a learner decides what to open. A quiz still being made must say so (not look like one to take),
 * one waiting for its warm-up must say that, and one that has been taken must show how the last try went and the best so
 * far, so "try again" is an informed choice.
 *
 * Use cases:
 * - says whether a quiz is about a topic or made from lessons
 * - gives the level and the number of questions, and no level while it is not known
 * - a quiz being made, one waiting for its warm-up and one that could not be made each say so and what to do
 * - a ready quiz that was never taken says to start; one being marked says so
 * - a taken quiz shows the last try, and the best only when it is better than the last; a good score is a success
 */
import { describe, expect, test } from "bun:test";

import { QuizList } from "./quiz-list";

const quiz = (fields: Partial<Parameters<typeof QuizList.status>[0]>) => ({ stage: "ready" as const, attempts_count: 0, latest_score: null, best_score: null, ...fields });

describe("what it is made from", () => {
  test("a topic or lessons", () => {
    expect(QuizList.kind({ source_type: "topic" })).toBe("Quick quiz on a topic");
    expect(QuizList.kind({ source_type: "lessons" })).toBe("Quick quiz from your lessons");
  });

  test("the level, once known, and the number of questions", () => {
    expect(QuizList.facts({ level: "foundation", num_questions: 10 })).toBe("Foundation level · 10 questions");
    expect(QuizList.facts({ level: "", num_questions: 5 })).toBe("5 questions");
  });
});

describe("where it stands", () => {
  test("a quiz that is not ready yet", () => {
    expect(QuizList.status(quiz({ stage: "preparing" }))).toEqual({ label: "Getting your questions ready", tone: "marigold", action: "Open" });
    expect(QuizList.status(quiz({ stage: "awaiting_calibration" })).action).toBe("Warm up");
    expect(QuizList.status(quiz({ stage: "failed" }))).toEqual({ label: "Couldn't be made", tone: "destructive-soft", action: "See why" });
  });

  test("a ready quiz that was never taken, and one being marked", () => {
    expect(QuizList.status(quiz({}))).toEqual({ label: "Ready to take", tone: "secondary", action: "Start" });
    expect(QuizList.status(quiz({ attempts_count: 1 }))).toEqual({ label: "Being marked", tone: "secondary", action: "See" });
  });

  test("a quiz that was taken shows the last try, and the best when it is better", () => {
    expect(QuizList.status(quiz({ attempts_count: 2, latest_score: 60, best_score: 80 }))).toEqual({ label: "Last try 60% · best 80%", tone: "insight", action: "Try again" });
    expect(QuizList.status(quiz({ attempts_count: 2, latest_score: 90, best_score: 90 }))).toEqual({ label: "Last try 90%", tone: "success", action: "Try again" });
  });
});
