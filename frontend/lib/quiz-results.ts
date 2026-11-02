import { PageLinks } from "@/lib/page-links";
import type { QuizAttempt, QuizDetail, QuizRecommendations } from "@/lib/types";

/** One weak concept of a lesson, with where to study it: its page when the lesson's index could place it. */
export type StudyLink = { concept: string; href: string; where: string; button: string; marksLost: number };

/** What to do next after a quiz attempt: a lesson to make, or lessons to study. */
export type Advice =
  | { kind: "none" }
  | { kind: "topic"; topics: string[]; canCreateLesson: boolean }
  | { kind: "lessons"; items: { title: string; level: string; topics: string[]; deleted: boolean; links: StudyLink[] }[] };

/** The words and links of a quiz result. Pure: the page passes in what the server said. */
export class QuizResults {
  /**
   * The advice: "Create a lesson for this" for a quiz about a topic, and for a quiz made from lessons which of them to
   * study, the lesson that lost most first, each weak concept with a link to the page that teaches it. A concept with no
   * page opens the lesson; a lesson that was deleted has no links.
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
        deleted: lesson.deleted ?? lesson.lesson_id === null,
        links: QuizResults.links(lesson),
      })),
    };
  }

  /** The links of one lesson. An answer without `links` (from before page links) falls back to its topics. */
  private static links(lesson: QuizRecommendations["lessons"][number]): StudyLink[] {
    if (lesson.lesson_id === null) return [];
    const id = lesson.lesson_id;
    const links = lesson.links ?? lesson.topics.map((concept) => ({ concept, page: "", heading: "", marks_lost: 0 }));
    return links.map((link) => ({
      concept: link.concept,
      href: PageLinks.href(id, link.page),
      where: PageLinks.where(link),
      button: PageLinks.button(link),
      marksLost: link.marks_lost,
    }));
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
