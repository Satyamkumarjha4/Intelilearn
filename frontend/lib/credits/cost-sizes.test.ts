/**
 * Unit under test: `CostSizes`, which turns what a screen is about to start into the question the quote endpoint is asked.
 *
 * Why: the price on a button must be the price the gate charges, and the gate reads the same hints the services send. A
 * screen that guessed a hint wrong would show a wrong price, or none at all (the server refuses hints it does not know).
 * These are the same hints the backend services send (`LessonService.size_of`, `MaterialService.size_of`,
 * `FollowupService.size_of`, `QuickQuizService`), and the screens never work out a price themselves.
 *
 * Use cases:
 * - a lesson from a Quick check covers its quiz stage only; a self-rated lesson covers everything
 * - a lesson that asks for sheets says how many and what they rest on (the Quick check, or nothing)
 * - a recommended lesson ("Make a lesson on this") says so; a lesson from a quiz result enters by it
 * - the mastery choice is the lesson or two sheets after a perfect Quick check
 * - a follow-up says its level; a test retake is always attempt 2 or later
 * - extra sheets say how many and what they rest on
 * - a new quiz says its count, source, number of sources and how its level is found; a retake says its count and source
 */
import { describe, expect, test } from "bun:test";

import { CostSizes } from "./cost-sizes";

describe("a new lesson", () => {
  test("from a Quick check covers its quiz stage", () => {
    expect(CostSizes.newLesson("diagnostic", "lesson", 0)).toEqual({
      action: "lesson.create",
      size: { entry: "diagnostic", intent: "lesson", origin: "direct", covers: "diagnostic" },
    });
  });

  test("by self-rating covers everything", () => {
    expect(CostSizes.newLesson("self_rating", "lesson", 0).size).toEqual({ entry: "self_rating", intent: "lesson", origin: "direct", covers: "all" });
  });

  test("that asks for sheets says how many, resting on the Quick check when there is one", () => {
    expect(CostSizes.newLesson("diagnostic", "sheets", 2).size).toEqual({
      entry: "diagnostic", intent: "sheets", origin: "direct", covers: "diagnostic", sheets: 2, grounding: "quiz",
    });
    expect(CostSizes.newLesson("self_rating", "sheets", 1).size).toMatchObject({ sheets: 1, grounding: "none", covers: "all" });
  });

  test("made from a recommendation, or from a quiz result, says where it came from", () => {
    expect(CostSizes.lessonOnThis().size).toMatchObject({ entry: "diagnostic", origin: "recommendation" });
    expect(CostSizes.lessonFromQuiz().size).toMatchObject({ entry: "quiz_result", origin: "quiz_result", covers: "all" });
  });
});

describe("the choices after a lesson is under way", () => {
  test("the mastery choice is the lesson, or two sheets resting on the Quick check", () => {
    expect(CostSizes.mastery("lesson")).toEqual({ action: "lesson.continue", size: { choice: "lesson", perfect: true } });
    expect(CostSizes.mastery("sheets")).toEqual({ action: "lesson.continue", size: { choice: "sheets_only", perfect: true, sheets: 2, grounding: "quiz" } });
  });

  test("a follow-up names its level", () => {
    expect(CostSizes.followup("advanced")).toEqual({
      action: "lesson.followup",
      size: { entry: "followup", intent: "lesson", origin: "followup", covers: "all", followup_level: "advanced" },
    });
  });

  test("a test retake is attempt 2 at the earliest", () => {
    expect(CostSizes.testRetake(1).size).toMatchObject({ attempt_no: 2 });
    expect(CostSizes.testRetake(4).size).toMatchObject({ attempt_no: 4 });
  });

  test("extra sheets say how many and what they rest on", () => {
    expect(CostSizes.sheets(2, "lesson")).toEqual({ action: "sheet.generate", size: { sheets: 2, grounding: "lesson" } });
  });
});

describe("a quiz", () => {
  test("a new one says its count, source, sources and how its level is found", () => {
    const topic = CostSizes.quiz({ num_questions: 10, source: { type: "topic", topic: "Sets" }, level: { mode: "calibration" } });
    const lessons = CostSizes.quiz({ num_questions: 15, source: { type: "lessons", lesson_ids: ["a", "b"] }, level: { mode: "self_rating", rating: 3 } });

    expect(topic).toEqual({ action: "quiz.create", size: { num_questions: 10, source_type: "topic", sources: 0, level_mode: "calibration" } });
    expect(lessons.size).toEqual({ num_questions: 15, source_type: "lessons", sources: 2, level_mode: "self_rating" });
  });

  test("a retake says its count and source", () => {
    expect(CostSizes.quizRetake(10, "lessons")).toEqual({ action: "quiz.retake", size: { num_questions: 10, source_type: "lessons" } });
  });
});
