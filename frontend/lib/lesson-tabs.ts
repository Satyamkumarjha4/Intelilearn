import type { LessonDetail } from "@/lib/types";

export type TabId = "lesson" | "test" | "sheets" | "answers";
export type TabTone = "marigold" | "success" | "destructive";
export type LessonTab = { id: TabId; label: string; badge?: { text: string; tone: TabTone } };
export type TabsInput = Pick<LessonDetail, "stage" | "sheets_only" | "test_status" | "latest_score" | "attempts_count" | "entry">;

/** The tabs of a ready lesson, and which one an address (`?tab=`) selects. */
export class LessonTabs {
  static of(lesson: TabsInput): LessonTab[] {
    if (lesson.stage !== "ready") return [];
    // A learner who rated themselves took no quick check, so there are no answers to look back at.
    const answers: LessonTab[] = lesson.entry === "self_rating" ? [] : [{ id: "answers", label: "Quick check answers" }];
    const sheets: LessonTab = { id: "sheets", label: "Study sheets" };
    if (lesson.sheets_only) return [sheets, ...answers];
    return [{ id: "lesson", label: "Lesson" }, { id: "test", label: "Test", badge: LessonTabs.testBadge(lesson) }, sheets, ...answers];
  }

  /** The tab the address asks for if the lesson has it, else the first one (null when there are no tabs). */
  static pick(tabs: LessonTab[], param: string | null): TabId | null {
    return tabs.find((tab) => tab.id === param)?.id ?? tabs[0]?.id ?? null;
  }

  private static testBadge(lesson: TabsInput): NonNullable<LessonTab["badge"]> {
    const percent = lesson.latest_score?.available
      ? Math.round((100 * lesson.latest_score.awarded) / lesson.latest_score.available)
      : null;
    switch (lesson.test_status) {
      case "generating":
        return { text: percent === null ? "Getting ready…" : `${percent}% · trying again`, tone: "marigold" };
      case "in_progress":
        return { text: percent === null ? "In progress" : `${percent}% · trying again`, tone: "marigold" };
      case "grading":
        return { text: "Grading…", tone: "marigold" };
      case "failed":
        return { text: "Needs another go at grading", tone: "destructive" };
      case "graded":
        return { text: percent === null ? `Attempt ${lesson.attempts_count}` : `${percent}% · attempt ${lesson.attempts_count}`, tone: "success" };
      default:
        return { text: "To do", tone: "marigold" };
    }
  }
}
