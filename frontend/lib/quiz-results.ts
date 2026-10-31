import type { QuizAttempt, QuizDetail } from "@/lib/types";

/** What to do next after a quiz attempt: a lesson to make, or lessons to study. */
export type Advice =
  | { kind: "none" }
  | { kind: "topic"; topics: string[]; canCreateLesson: boolean }
  | { kind: "lessons"; items: { title: string; level: string; topics: string[]; href: string | null }[] };

/** The words and links of a quiz result. Pure: the page passes in what the server said. */
export class QuizResults {
  /**
   * The advice: "Create a lesson for this" for a quiz about a topic, and for a quiz made from lessons which of them to
   * study, with the concepts that lost marks (the lesson that lost most first; links go to the lesson, page deep links
   * come with concept tags).
   */
  static advice(quiz: Pick<QuizDetail, "can_create_lesson">, attempt: Pick<QuizAttempt, "status" | "recommendations">): Advice {
    const tips = attempt.recommendations;
    if (attempt.status !== "graded" || tips === null) return { kind: "none" };
    if (tips.kind === "topic") return { kind: "topic", topics: tips.topics, canCreateLesson: quiz.can_create_lesson };
    return {
      kind: "lessons",
      items: tips.lessons.map((lesson) => ({
        title: lesson.title,
        level: lesson.level,
        topics: lesson.topics,
        href: lesson.lesson_id ? `/lessons/${lesson.lesson_id}` : null,
      })),
    };
  }

  /** "7 of 10 marks", or nothing while the attempt is not marked yet. */
  static marks(attempt: Pick<QuizAttempt, "awarded" | "available">): string {
    return attempt.awarded === null || attempt.available === null ? "" : `${attempt.awarded} of ${attempt.available} marks`;
  }

  /** What the Try again button says; a quiz can always be taken again, with new questions. */
  static readonly RETAKE = "Try again with new questions";
  static readonly RETAKE_NOTE = "Every try has new questions. Your tries are compared with each other, and your best is kept.";

  /** The words for the lesson maker button, and for what happens when it is pressed. */
  static readonly CREATE_LESSON = "Create a lesson for this";
  static readonly CREATE_HINT = "We'll write a lesson that starts where this quiz showed you are.";

  /** How a lesson is shown in the advice: its level next to its title, if it has one. */
  static lessonLine(item: { title: string; level: string }): string {
    return item.level ? `${item.title} · ${item.level.charAt(0).toUpperCase()}${item.level.slice(1)}` : item.title;
  }
}
