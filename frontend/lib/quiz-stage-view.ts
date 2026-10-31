import type { QuizDetail } from "@/lib/types";

/** What the quiz page shows, decided by what the server says the quiz is. */
export type QuizView =
  | { kind: "building"; runId: string | null }
  | { kind: "calibration" }
  | { kind: "failed"; message: string }
  | { kind: "taking"; attemptId: string }
  | { kind: "preparing"; runId: string | null }
  | { kind: "results"; attemptId: string }
  | { kind: "empty" };

/** Which screen a quiz is on, like a lesson's journey: building, calibration, taking, results. Pure. */
export class QuizStageView {
  static readonly FAILED = "We couldn't make this quiz. Nothing was used up: you can start again.";

  static of(quiz: QuizDetail): QuizView {
    switch (quiz.stage) {
      case "failed":
        return { kind: "failed", message: quiz.error.trim() || QuizStageView.FAILED };
      case "preparing":
        return { kind: "building", runId: quiz.run_id };
      case "awaiting_calibration":
        return { kind: "calibration" };
      case "ready":
        return QuizStageView.ready(quiz);
    }
  }

  private static ready(quiz: QuizDetail): QuizView {
    const open = quiz.open_attempt;
    if (open?.status === "in_progress") return { kind: "taking", attemptId: open.id };
    if (open?.status === "generating") return { kind: "preparing", runId: quiz.run_id };
    const over = quiz.attempts.filter((a) => a.status !== "generating" && a.status !== "in_progress");
    const latest = over.at(-1);
    return latest ? { kind: "results", attemptId: latest.id } : { kind: "empty" };
  }

  /** "Foundation level · 10 questions · 2 lessons", for under the title. */
  static facts(quiz: QuizDetail): string {
    const { num_questions: count } = quiz.config;
    const parts = [
      quiz.level ? `${QuizStageView.capital(quiz.level)} level` : "",
      `${count} ${count === 1 ? "question" : "questions"}`,
      quiz.source_type === "lessons" ? `${quiz.sources.length} ${quiz.sources.length === 1 ? "lesson" : "lessons"}` : "",
    ];
    return parts.filter(Boolean).join(" · ");
  }

  static capital(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
}
