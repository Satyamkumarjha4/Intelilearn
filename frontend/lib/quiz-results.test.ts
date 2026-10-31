/**
 * Unit under test: `QuizResults`, the words and links of a quiz result.
 *
 * Why: the result is where a quiz leads somewhere. A quiz about a topic offers a lesson on it; a quiz made from lessons
 * must send the learner back to the right lesson, saying what to look at there, and must not link a lesson that was
 * deleted. Advice before the attempt is marked would be advice on a guess.
 *
 * Use cases:
 * - no advice until the attempt is graded, or when the server gave none
 * - a topic quiz offers the lesson (when the quiz can make one) with the concepts that lost marks
 * - a quiz from lessons lists the lessons to study in the server's order, each with its concepts and a link to the lesson,
 *   and no link for a lesson that has been deleted
 * - writes the marks, and nothing while the attempt is not marked
 * - the words of the buttons
 */
import { describe, expect, test } from "bun:test";

import { QuizResults } from "./quiz-results";
import type { QuizAttempt } from "./types";

const attempt = (fields: Partial<QuizAttempt>): Pick<QuizAttempt, "status" | "recommendations"> =>
  ({ status: "graded", recommendations: null, ...fields }) as Pick<QuizAttempt, "status" | "recommendations">;

describe("the advice", () => {
  test("none until the attempt is graded, or when there is none", () => {
    const tips = { kind: "topic" as const, topics: ["A"], lessons: [] };

    expect(QuizResults.advice({ can_create_lesson: true }, attempt({ status: "grading", recommendations: tips }))).toEqual({ kind: "none" });
    expect(QuizResults.advice({ can_create_lesson: true }, attempt({ recommendations: null }))).toEqual({ kind: "none" });
  });

  test("a topic quiz offers a lesson when it can make one", () => {
    const tips = { kind: "topic" as const, topics: ["Loops", "Recursion"], lessons: [] };

    expect(QuizResults.advice({ can_create_lesson: true }, attempt({ recommendations: tips }))).toEqual({
      kind: "topic", topics: ["Loops", "Recursion"], canCreateLesson: true,
    });
    expect(QuizResults.advice({ can_create_lesson: false }, attempt({ recommendations: tips }))).toMatchObject({ canCreateLesson: false });
  });

  test("a quiz from lessons lists the lessons to study, linked unless the lesson was deleted", () => {
    const tips = {
      kind: "lessons" as const,
      topics: [],
      lessons: [
        { lesson_id: "l1", title: "Binary search", level: "foundation", marks_lost: 4, topics: ["Halving"] },
        { lesson_id: null, title: "Sorting", level: "expert", marks_lost: 2, topics: ["Merge"] },
      ],
    };

    expect(QuizResults.advice({ can_create_lesson: false }, attempt({ recommendations: tips }))).toEqual({
      kind: "lessons",
      items: [
        { title: "Binary search", level: "foundation", topics: ["Halving"], href: "/lessons/l1" },
        { title: "Sorting", level: "expert", topics: ["Merge"], href: null },
      ],
    });
  });
});

describe("the words", () => {
  test("marks, once marked", () => {
    expect(QuizResults.marks({ awarded: 7, available: 10 })).toBe("7 of 10 marks");
    expect(QuizResults.marks({ awarded: null, available: null })).toBe("");
  });

  test("a lesson in the advice carries its level", () => {
    expect(QuizResults.lessonLine({ title: "Binary search", level: "foundation" })).toBe("Binary search · Foundation");
    expect(QuizResults.lessonLine({ title: "Binary search", level: "" })).toBe("Binary search");
  });

  test("the buttons say what they do", () => {
    expect(QuizResults.RETAKE).toBe("Try again with new questions");
    expect(QuizResults.CREATE_LESSON).toBe("Create a lesson for this");
  });
});
