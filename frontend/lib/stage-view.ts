import type { Band, LessonDetail, QuizResultSummary, Route } from "@/lib/types";

export const BAND_ORDER: Band[] = ["basic", "easy_moderate", "moderate", "moderate_hard", "hard"];

/** How a learner reads a difficulty band. */
export const BAND_LABELS: Record<Band, string> = {
  basic: "Basics",
  easy_moderate: "Easy applications",
  moderate: "Standard problems",
  moderate_hard: "Edge cases",
  hard: "Expert",
};

/** Which screen of the lesson page a lesson is on (docs/frontend.md, "the stage-driven view"). */
export type ScreenKind =
  | "progress"
  | "diagnostic"
  | "prerequisite"
  | "choice"
  | "material"
  | "lesson"
  | "failed";

export class StageView {
  /**
   * A lesson with an active run is always on the progress screen: right after Retry the stage is still `failed`
   * until the first node runs, and showing the error again would invite a second click.
   */
  static of(lesson: Pick<LessonDetail, "stage" | "route" | "active_run_id">): ScreenKind {
    const waiting = lesson.stage.startsWith("awaiting_");
    if (lesson.active_run_id && !waiting) return "progress";
    switch (lesson.stage) {
      case "awaiting_diagnostic":
        return "diagnostic";
      case "awaiting_prerequisite":
        return "prerequisite";
      case "awaiting_choice":
        return "choice";
      case "failed":
        return "failed";
      case "ready":
        return lesson.route === "mastery" ? "material" : "lesson";
      default:
        return "progress";
    }
  }

  /** What happens next, in words, for the card shown right after a diagnostic is scored. */
  static nextStep(route: Route | undefined, level = ""): string {
    switch (route) {
      case "prerequisite":
        return "We'll check a few foundations first.";
      case "mastery":
        return "You already know this well. Pick a study sheet next.";
      case "lesson":
        return level ? `Building your lesson at ${level} level.` : "Building your lesson.";
      default:
        return "";
    }
  }

  /** The score per band, easiest first (the API's JSON object does not keep its key order). */
  static bandsOf(result: QuizResultSummary): [Band, [number, number]][] {
    return BAND_ORDER.flatMap((band) => (result.by_band[band] ? [[band, result.by_band[band]] as [Band, [number, number]]] : []));
  }
}
