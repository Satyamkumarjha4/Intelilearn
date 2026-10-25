import type { LearnerTestQuestion, QuestionResult } from "@/lib/types";

export type Status = "right" | "partial" | "wrong" | "pending";
export type AnswerText = { text: string; code?: boolean };

const LETTERS = "ABCDEF";

/** How a submitted test is told to the learner (the read-only results screen). */
export class TestReport {
  /** An encouraging line for the score, warm at every level. */
  static headline(percent: number): string {
    if (percent >= 90) return "Outstanding work!";
    if (percent >= 75) return "Great job!";
    if (percent >= 50) return "Solid effort. You're getting there.";
    if (percent >= 25) return "A good start. Let's build on it.";
    return "This one was tough, and that's useful to know.";
  }

  static status(row: QuestionResult): Status {
    if (row.awarded === null) return "pending";
    if (row.awarded >= row.marks) return "right";
    return row.awarded > 0 ? "partial" : "wrong";
  }

  static stats(rows: QuestionResult[]) {
    const count = (status: Status) => rows.filter((row) => TestReport.status(row) === status).length;
    return {
      correct: count("right"),
      partial: count("partial"),
      missed: count("wrong"),
      aiGraded: rows.filter((row) => row.graded_by === "model").length,
      pending: count("pending"),
    };
  }

  /** What the learner answered, as they would say it; null when they gave no answer. */
  static yourAnswer(question: LearnerTestQuestion, value: unknown): AnswerText | null {
    if (question.type === "mcq") return typeof value === "number" ? TestReport.option(question, value) : null;
    if (typeof value !== "string" || value.trim() === "") return null;
    const text = question.type === "numerical" && question.unit ? `${value.trim()} ${question.unit}` : value;
    return question.type === "code" ? { text, code: true } : { text };
  }

  /** The right answer, from the marking scheme the server shows once the test is submitted; null when it has none. */
  static correctAnswer(question: LearnerTestQuestion, solution: Record<string, unknown>): AnswerText | null {
    if (question.type === "mcq") return typeof solution.correct_index === "number" ? TestReport.option(question, solution.correct_index) : null;
    if (question.type === "numerical") {
      if (typeof solution.answer !== "number") return null;
      const unit = typeof solution.unit === "string" && solution.unit ? ` ${solution.unit}` : "";
      return { text: `${solution.answer}${unit}` };
    }
    if (question.type === "code") return typeof solution.reference_solution === "string" ? { text: solution.reference_solution, code: true } : null;
    return typeof solution.model_answer === "string" ? { text: solution.model_answer } : null;
  }

  /** The request that makes a lesson on a topic worth another look. */
  static followUp(lessonTitle: string, topic: string): { topic: string; context: string } {
    const named = topic.trim().slice(0, 200);
    return {
      topic: named.length >= 2 ? named : `${lessonTitle} (${named})`.slice(0, 200),
      context: `Follow-up to my ${lessonTitle.slice(0, 200)} test`,
    };
  }

  static followUpError(status: number | undefined): string {
    return status === 429
      ? "You've started a lot of lessons just now. Please wait a little while and try again."
      : "We couldn't start that lesson. Please try again.";
  }

  private static option(question: LearnerTestQuestion, index: number): AnswerText | null {
    const text = question.options?.[index];
    return text === undefined ? null : { text: `${LETTERS[index]}. ${text}` };
  }
}
