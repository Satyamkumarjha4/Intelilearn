/**
 * Unit under test: `QuizMessages`, what the quiz screens say when the server says no.
 *
 * Why: a quiz is made, retaken and turned into a lesson through endpoints that can refuse for many reasons (a rule of
 * the request, a gate that says no, a busy server, a lesson that is gone). Every one needs words a learner can act on,
 * and an action the server refused must be told in the server's own words, the same on every screen.
 *
 * Use cases:
 * - a refused action is told in its own words
 * - making a quiz: a missing lesson, a rate limit, no model, a wrong field (its message), a bad request (the server's
 *   message), and anything else in words of ours
 * - a new try: the daily limit, a lesson that was deleted, a refused action, anything else
 * - a lesson from a result: a rate limit, the server's message, words of ours for a failure that is not the API's
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { QuizMessages } from "./quiz-messages";

const refused = new ApiError(403, "action_refused", "Not available on your plan.");

describe("making a quiz", () => {
  test("a refused action is told in its own words", () => {
    expect(QuizMessages.make(refused)).toBe("Not available on your plan.");
  });

  test.each([
    [new ApiError(404, "not_found", "x"), "One of those lessons isn't available any more. Pick again."],
    [new ApiError(429, "throttled", "x"), "You're going a bit fast. Wait a moment and try again."],
    [new ApiError(503, "llm_not_configured", "x"), "Quizzes aren't set up yet. Please try again later."],
    [new ApiError(400, "invalid", "Fix it.", { types: ["Pick at least one kind of question."] }), "Pick at least one kind of question."],
    [new ApiError(400, "source_not_usable", "“Sheets” is study sheets only, so there is nothing to ask about."), "“Sheets” is study sheets only, so there is nothing to ask about."],
    [new ApiError(500, "error", "boom"), QuizMessages.MAKE],
    [new TypeError("network"), QuizMessages.MAKE],
  ])("%p reads %p", (error, text) => {
    expect(QuizMessages.make(error)).toBe(text);
  });
});

describe("a new try", () => {
  test.each([
    [refused, "Not available on your plan."],
    [new ApiError(429, "retake_limit", "x"), "That's enough tries for today. You can try again tomorrow."],
    [new ApiError(409, "source_missing", "x"), "A lesson this quiz was made from has been deleted, so it can't be taken again. Make a new quiz."],
    [new ApiError(409, "wrong_stage", "The quiz is not ready."), "The quiz is not ready."],
    [new TypeError("network"), "We couldn't start a new try. Please try again."],
  ])("%p reads %p", (error, text) => {
    expect(QuizMessages.retake(error)).toBe(text);
  });
});

describe("a lesson from a result", () => {
  test.each([
    [refused, "Not available on your plan."],
    [new ApiError(429, "throttled", "x"), "You're making lessons very fast. Wait a moment and try again."],
    [new ApiError(400, "not_a_topic_quiz", "Only a quiz about a topic can become a lesson."), "Only a quiz about a topic can become a lesson."],
    [new TypeError("network"), "We couldn't start that lesson. Please try again."],
  ])("%p reads %p", (error, text) => {
    expect(QuizMessages.createLesson(error)).toBe(text);
  });
});
