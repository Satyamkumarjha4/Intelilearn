import type { LessonDetail } from "@/lib/types";

export type JourneyStepState = "done" | "now" | "todo";
export type JourneyStep = { label: string; state: JourneyStepState; failed: boolean };
export type JourneyInput = Pick<LessonDetail, "stage" | "route" | "assessment" | "results" | "test_status" | "active_run_id">;

const LESSON_STEPS = ["Diagnose", "Your level", "Learn", "Test", "Revisit"] as const;
const MASTERY_STEPS = ["Diagnose", "Mastered", "Pick a sheet", "Study"] as const;

/**
 * The journey stepper at the top of the lesson workspace: where the learner is, from the lesson's stage, route and
 * what it already holds. Exactly one step is "now", everything before it is done and everything after it is to do.
 */
export class Journey {
  /** The small tag next to the title: the level once it is known, else the route. */
  static tag(lesson: Pick<LessonDetail, "route" | "level" | "assessment">): string | null {
    const level = (lesson.assessment?.level || lesson.level || "").trim();
    if (level) return `${level.charAt(0).toUpperCase()}${level.slice(1).toLowerCase()} level`;
    return { prerequisite: "Foundations first", lesson: "Lesson", mastery: "Mastery" }[lesson.route as string] ?? null;
  }

  static of(lesson: JourneyInput): JourneyStep[] {
    const mastery = lesson.route === "mastery";
    const labels: readonly string[] = mastery ? MASTERY_STEPS : LESSON_STEPS;
    const now = mastery ? Journey.masteryNow(lesson) : Journey.lessonNow(lesson);
    const failed = lesson.stage === "failed" && !lesson.active_run_id;
    return labels.map((label, index) => ({
      label,
      state: index < now ? "done" : index === now ? "now" : "todo",
      failed: failed && index === now,
    }));
  }

  /** Index of the current step of the lesson route. */
  private static lessonNow(lesson: JourneyInput): number {
    const [DIAGNOSE, LEVEL, LEARN, TEST, REVISIT] = [0, 1, 2, 3, 4];
    switch (lesson.stage) {
      case "preparing_diagnostic":
      case "awaiting_diagnostic":
      case "awaiting_prerequisite":
        return DIAGNOSE;
      case "generating_lesson":
        return lesson.assessment ? LEARN : LEVEL;
      case "ready":
        if (lesson.test_status === "grading" || lesson.test_status === "graded") return REVISIT;
        return lesson.test_status === "failed" ? TEST : LEARN;
      case "failed":
        // The lesson does not say where it failed, but what it holds does: no answered quiz, no assessment, or both.
        if (lesson.assessment) return LEARN;
        return lesson.results.diagnostic ? LEVEL : DIAGNOSE;
      default:
        return DIAGNOSE;
    }
  }

  /** Index of the current step of the mastery route. */
  private static masteryNow(lesson: JourneyInput): number {
    return lesson.stage === "awaiting_choice" ? 2 : 3;
  }
}
