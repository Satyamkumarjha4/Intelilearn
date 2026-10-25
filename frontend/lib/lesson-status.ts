import type { LessonSummary, Stage } from "@/lib/types";

export type PillTone = "marigold" | "primary" | "success" | "insight" | "destructive";
export type Pill = { label: string; tone: PillTone; spinner: boolean; action: string };

/** The chips above the list, each a set of stages for the `?stage=` filter (none for All). */
export const LESSON_FILTERS: { label: string; stages: Stage[] }[] = [
  { label: "All", stages: [] },
  { label: "Needs you", stages: ["awaiting_diagnostic", "awaiting_prerequisite", "awaiting_choice"] },
  { label: "Building", stages: ["preparing_diagnostic", "generating_material", "generating_lesson"] },
  { label: "Ready", stages: ["ready"] },
  { label: "Couldn't finish", stages: ["failed"] },
];

const pill = (label: string, tone: PillTone, action: string, spinner = false): Pill => ({ label, tone, spinner, action });

/** How a lesson in the list is described: its status as the next action, a kind line, and how long ago. */
export class LessonStatus {
  /** The pages of a lesson book. */
  static readonly PAGES = 3;

  /** `pagesRead`: how many of the book's pages this browser has seen (a ready lesson only says "Take the test" after all). */
  static of(lesson: LessonSummary, pagesRead = 0): Pill {
    switch (lesson.stage) {
      case "preparing_diagnostic":
        return pill("Preparing your quick check", "primary", "Watch", true);
      case "awaiting_diagnostic":
        return pill("Your quick check is waiting", "marigold", "Start");
      case "awaiting_prerequisite":
        return pill("A few basics are waiting", "marigold", "Start");
      case "awaiting_choice":
        return pill("You aced the check · pick a sheet", "insight", "Pick a sheet");
      case "generating_material":
        return pill("Writing your study sheet", "primary", "Watch", true);
      case "generating_lesson":
        return pill("Building your lesson", "primary", "Watch", true);
      case "failed":
        return pill("Couldn't finish building", "destructive", "Try again");
      case "ready":
        return LessonStatus.ready(lesson, pagesRead);
    }
  }

  /** "Lesson · Beginner", "Study sheets · Mastered", or "Quick check" while the route is not known yet. */
  static kind(lesson: Pick<LessonSummary, "route" | "level">): string {
    if (lesson.route === "mastery") return "Study sheets · Mastered";
    if (!lesson.route) return "Quick check";
    const level = lesson.level.trim();
    return level ? `Lesson · ${level.charAt(0).toUpperCase()}${level.slice(1).toLowerCase()}` : "Lesson";
  }

  /** It waits for an answer, or it is a ready lesson whose test has not been taken. */
  static needsLearner(lesson: LessonSummary): boolean {
    if (lesson.stage.startsWith("awaiting_")) return true;
    return lesson.stage === "ready" && lesson.route !== "mastery" && lesson.test_status === "not_started";
  }

  /** The lesson to offer first: the most recently updated one that needs the learner. */
  static pickContinue(lessons: LessonSummary[]): LessonSummary | null {
    const waiting = lessons.filter(LessonStatus.needsLearner);
    return waiting.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0] ?? null;
  }

  static ago(iso: string, now = Date.now(), locale?: string): string {
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return "";
    const minutes = Math.floor((now - then) / 60_000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
    const days = Math.floor(hours / 24);
    if (days === 1) return "yesterday";
    if (days < 7) return `${days} days ago`;
    return new Date(then).toLocaleDateString(locale, { dateStyle: "medium", timeZone: "UTC" });
  }

  private static ready(lesson: LessonSummary, pagesRead: number): Pill {
    if (lesson.route === "mastery") {
      const sheets = lesson.material_count;
      return pill(sheets ? `You aced the check · ${sheets} ${sheets === 1 ? "sheet" : "sheets"}` : "You aced the check", "insight", "Open");
    }
    switch (lesson.test_status) {
      case "grading":
        return pill("Marking your test", "primary", "Open", true);
      case "failed":
        return pill("Test needs marking again", "destructive", "Open");
      case "graded": {
        const score = lesson.test_score;
        const percent = score && score.available ? ` · ${Math.round((100 * score.awarded) / score.available)}%` : "";
        return pill(`Test done${percent}`, "success", "Open");
      }
      default:
        return pagesRead >= LessonStatus.PAGES ? pill("Take the test", "marigold", "Take the test") : pill("Ready", "success", "Open");
    }
  }
}
