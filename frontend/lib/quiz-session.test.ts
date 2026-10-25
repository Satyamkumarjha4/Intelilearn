/**
 * Unit under test: `QuizSession`, a learner's progress through a quiz.
 *
 * Why: the API refuses a quiz with a missing answer, and a lost answer on "back" would make the learner redo work.
 * "I don't know" must be a real answer, not an empty one.
 *
 * Use cases:
 * - starts at the first question with no progress
 * - records an answer for the current question, including "I don't know", and keeps it when moving back and forth
 * - moves forward and back within the bounds of the quiz
 * - reports progress and when every question is answered
 * - finds the first unanswered question
 * - rejects an option that does not exist
 * - builds the submit payload only when complete
 */
import { describe, expect, test } from "bun:test";

import { DONT_KNOW, QuizSession } from "./quiz-session";

const questions = ["q1", "q2", "q3"].map((id) => ({ id, question: id, options: ["a", "b", "c", "d"] }));

describe("QuizSession", () => {
  test("starts at the first question with no progress", () => {
    const quiz = new QuizSession(questions);

    expect(quiz.current?.id).toBe("q1");
    expect([quiz.answered, quiz.progress, quiz.isComplete]).toEqual([0, 0, false]);
  });

  test("records answers, including I don't know, and keeps them across navigation", () => {
    const quiz = new QuizSession(questions);

    quiz.answer(2);
    quiz.next();
    quiz.answer(DONT_KNOW);
    quiz.back();

    expect(quiz.answerOf("q1")).toBe(2);
    expect(quiz.answerOf("q2")).toBe(DONT_KNOW);
    expect(quiz.answerOf("q3")).toBeUndefined();
  });

  test("changing an answer replaces it", () => {
    const quiz = new QuizSession(questions);

    quiz.answer(1);
    quiz.answer(3);

    expect(quiz.answerOf("q1")).toBe(3);
    expect(quiz.answered).toBe(1);
  });

  test("stays within the quiz when moving", () => {
    const quiz = new QuizSession(questions);

    quiz.back();
    expect(quiz.index).toBe(0);
    quiz.next();
    quiz.next();
    quiz.next();
    expect(quiz.index).toBe(2);
    expect(quiz.isLast).toBe(true);
  });

  test("reports progress and completeness", () => {
    const quiz = new QuizSession(questions);

    quiz.answer(0);
    quiz.next();
    quiz.answer(0);
    expect(quiz.progress).toBeCloseTo(2 / 3);
    expect(quiz.isComplete).toBe(false);

    quiz.next();
    quiz.answer(DONT_KNOW);
    expect(quiz.isComplete).toBe(true);
  });

  test("finds the first unanswered question", () => {
    const quiz = new QuizSession(questions);
    quiz.answer(0);
    quiz.next();
    quiz.next();
    quiz.answer(0);

    expect(quiz.firstUnanswered()).toBe(1);
  });

  test("rejects an option that does not exist", () => {
    const quiz = new QuizSession(questions);

    expect(() => quiz.answer(4)).toThrow(RangeError);
    expect(() => quiz.answer(-1)).toThrow(RangeError);
    expect(() => quiz.answer(1.5)).toThrow(RangeError);
    expect(quiz.answered).toBe(0);
  });

  test("builds the submit payload only when complete", () => {
    const quiz = new QuizSession(questions);
    quiz.answer(1);
    expect(() => quiz.payload()).toThrow("Answer every question");

    quiz.next();
    quiz.answer(DONT_KNOW);
    quiz.next();
    quiz.answer(0);

    expect(quiz.payload()).toEqual({ q1: 1, q2: "dont_know", q3: 0 });
  });

  test("an empty quiz is never complete", () => {
    expect(new QuizSession([]).isComplete).toBe(false);
  });
});
