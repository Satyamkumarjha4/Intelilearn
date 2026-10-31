import type { QuizSummary } from "@/lib/types";

export type QuizTone = "success" | "marigold" | "destructive-soft" | "secondary" | "insight";
export type QuizStatus = { label: string; tone: QuizTone; action: string };

/** How a quick quiz reads in the list: what it is, where it stands as a sentence, and what to do next. Pure. */
export class QuizList {
  /** "Quiz about a topic" or "Quiz from 3 lessons"; the list does not know the number, so lessons are just lessons. */
  static kind(quiz: Pick<QuizSummary, "source_type">): string {
    return quiz.source_type === "topic" ? "Quick quiz on a topic" : "Quick quiz from your lessons";
  }

  /** "Foundation level · 10 questions". */
  static facts(quiz: Pick<QuizSummary, "level" | "num_questions">): string {
    const level = quiz.level ? `${quiz.level.charAt(0).toUpperCase()}${quiz.level.slice(1)} level · ` : "";
    return `${level}${quiz.num_questions} questions`;
  }

  static status(quiz: Pick<QuizSummary, "stage" | "attempts_count" | "latest_score" | "best_score">): QuizStatus {
    switch (quiz.stage) {
      case "preparing":
        return { label: "Getting your questions ready", tone: "marigold", action: "Open" };
      case "awaiting_calibration":
        return { label: "Your warm-up is waiting", tone: "marigold", action: "Warm up" };
      case "failed":
        return { label: "Couldn't be made", tone: "destructive-soft", action: "See why" };
      case "ready":
        break;
    }
    if (quiz.latest_score === null) return { label: quiz.attempts_count ? "Being marked" : "Ready to take", tone: "secondary", action: quiz.attempts_count ? "See" : "Start" };
    const best = quiz.best_score !== null && quiz.best_score > quiz.latest_score ? ` · best ${quiz.best_score}%` : "";
    return { label: `Last try ${quiz.latest_score}%${best}`, tone: quiz.latest_score >= 75 ? "success" : "insight", action: "Try again" };
  }
}
