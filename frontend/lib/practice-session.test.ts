/**
 * Unit under test: `PracticeSession`, a learner's work on a practice sheet: answers, revealed solutions and the marks.
 *
 * Why: practice is repeatable and nothing is stored on the server, so this is the only record of what the learner has
 * typed. Losing an answer on reveal, or sending blank answers as if they were given, would show a wrong score.
 *
 * Use cases:
 * - records multiple-choice answers as numbers and numerical or written answers as text
 * - clearing a text answer removes it
 * - the payload carries only the answered questions
 * - revealing a solution is remembered per question
 * - marks from the server are kept per question and can be looked up
 * - starting again clears answers, reveals and marks
 */
import { describe, expect, test } from "bun:test";

import { PracticeSession } from "./practice-session";
import type { PracticeGrade, PracticeQuestion } from "./types";

const question = (id: string, type: PracticeQuestion["type"]): PracticeQuestion => ({
  id,
  type,
  concept: "c",
  difficulty: "easy",
  marks: 2,
  question: id,
});
const questions = [question("t1", "mcq"), question("t2", "numerical"), question("t3", "short_answer")];

describe("PracticeSession", () => {
  test("records choices as numbers and typed answers as text", () => {
    const session = new PracticeSession(questions);

    session.setAnswer("t1", 2);
    session.setAnswer("t2", "4.0");
    session.setAnswer("t3", "halve the range");

    expect(session.answerOf("t1")).toBe(2);
    expect(session.answerOf("t2")).toBe("4.0");
    expect(session.answered).toBe(3);
  });

  test("clearing a text answer removes it", () => {
    const session = new PracticeSession(questions);
    session.setAnswer("t3", "x");

    session.setAnswer("t3", "   ");

    expect(session.answerOf("t3")).toBeUndefined();
    expect(session.answered).toBe(0);
  });

  test("the payload carries only the answered questions", () => {
    const session = new PracticeSession(questions);
    session.setAnswer("t1", 0);
    session.setAnswer("t3", " a ");

    expect(session.payload()).toEqual({ t1: 0, t3: "a" });
  });

  test("revealing a solution is remembered per question", () => {
    const session = new PracticeSession(questions);

    session.reveal("t2");

    expect(session.isRevealed("t2")).toBe(true);
    expect(session.isRevealed("t1")).toBe(false);
    expect(session.revealed).toEqual(["t2"]);
  });

  test("keeps the marks from the server per question", () => {
    const session = new PracticeSession(questions);
    const grade: PracticeGrade = {
      score: { awarded: 2, available: 4, open_marks: 2, correct: 1, marked: 2 },
      results: [
        { id: "t1", correct: true, marks: 2, awarded: 2, solution: { correct_index: 2 } },
        { id: "t2", correct: false, marks: 2, awarded: 0, solution: { answer: 4 } },
        { id: "t3", correct: null, marks: 2, awarded: null, solution: { model_answer: "m" } },
      ],
    };

    session.mark(grade);

    expect(session.gradeOf("t1")?.correct).toBe(true);
    expect(session.gradeOf("t3")?.correct).toBeNull();
    expect(session.score).toEqual(grade.score);
    expect(session.gradeOf("zzz")).toBeUndefined();
  });

  test("starting again clears answers, reveals and marks", () => {
    const session = new PracticeSession(questions);
    session.setAnswer("t1", 1);
    session.reveal("t1");
    session.mark({ score: { awarded: 0, available: 0, open_marks: 0, correct: 0, marked: 0 }, results: [] });

    session.reset();

    expect([session.answered, session.revealed.length, session.score]).toEqual([0, 0, null]);
  });
});
