/**
 * Unit under test: `QuizStageView`, which screen the quiz page shows.
 *
 * Why: like a lesson, a quiz is driven by the server's stage: building, waiting for the warm-up, ready to take, being
 * retaken, over. A page that shows the wrong one (the questions while the retake is still being written, a failure as
 * a spinner) strands the learner, and a refresh must always land where they were.
 *
 * Use cases:
 * - a quiz that failed shows its reason, or words of ours when it has none
 * - a quiz being made shows its progress (with the run to follow); one waiting for calibration shows the walk
 * - a ready quiz with an attempt in progress shows it; one whose retake is being written shows that wait
 * - a ready quiz with no attempt open shows the result of the latest attempt that is over (graded, being marked, or
 *   failed to mark)
 * - says the facts under the title: level, number of questions, number of lessons
 */
import { describe, expect, test } from "bun:test";

import { QuizStageView } from "./quiz-stage-view";
import type { QuizDetail } from "./types";

const quiz = (fields: Partial<QuizDetail>): QuizDetail =>
  ({
    stage: "ready", error: "", run_id: null, open_attempt: null, attempts: [], level: "foundation", source_type: "topic",
    sources: [], config: { num_questions: 10, types: ["mcq"], level_mode: "self_rating", self_rating: 3 }, ...fields,
  }) as unknown as QuizDetail;

const attempt = (id: string, status: string) => ({ id, attempt_no: 1, status }) as unknown as QuizDetail["attempts"][number];

describe("the screen", () => {
  test("a quiz that failed shows its reason or ours", () => {
    expect(QuizStageView.of(quiz({ stage: "failed", error: "No model answered." }))).toEqual({ kind: "failed", message: "No model answered." });
    expect(QuizStageView.of(quiz({ stage: "failed", error: "  " }))).toEqual({ kind: "failed", message: QuizStageView.FAILED });
  });

  test("a quiz being made, and one waiting for the warm-up", () => {
    expect(QuizStageView.of(quiz({ stage: "preparing", run_id: "r1" }))).toEqual({ kind: "building", runId: "r1" });
    expect(QuizStageView.of(quiz({ stage: "awaiting_calibration" }))).toEqual({ kind: "calibration" });
  });

  test("an attempt in progress is taken, and a retake being written is waited for", () => {
    const taking = quiz({ open_attempt: { id: "a2", attempt_no: 2, status: "in_progress" }, attempts: [attempt("a1", "graded"), attempt("a2", "in_progress")] });
    const writing = quiz({ run_id: "r2", open_attempt: { id: "a2", attempt_no: 2, status: "generating" }, attempts: [attempt("a1", "graded")] });

    expect(QuizStageView.of(taking)).toEqual({ kind: "taking", attemptId: "a2" });
    expect(QuizStageView.of(writing)).toEqual({ kind: "preparing", runId: "r2" });
  });

  test.each(["graded", "grading", "failed"])("with nothing open the latest %s attempt is the result", (status) => {
    const view = QuizStageView.of(quiz({ attempts: [attempt("a1", "graded"), attempt("a2", status)] }));

    expect(view).toEqual({ kind: "results", attemptId: "a2" });
  });

  test("an attempt that has not started is not a result", () => {
    expect(QuizStageView.of(quiz({ attempts: [attempt("a1", "generating")] }))).toEqual({ kind: "empty" });
  });
});

describe("the facts under the title", () => {
  test("level, questions and lessons", () => {
    const lessons = quiz({ source_type: "lessons", level: "proficient", sources: [{}, {}] as QuizDetail["sources"] });

    expect(QuizStageView.facts(lessons)).toBe("Proficient level · 10 questions · 2 lessons");
  });

  test("a quiz about a topic has no lessons and one whose level is not known yet has none", () => {
    expect(QuizStageView.facts(quiz({ level: "" }))).toBe("10 questions");
    expect(QuizStageView.facts(quiz({ source_type: "lessons", sources: [{}] as QuizDetail["sources"], config: { num_questions: 5 } as QuizDetail["config"] }))).toBe(
      "Foundation level · 5 questions · 1 lesson",
    );
  });
});
