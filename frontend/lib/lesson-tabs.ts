import type { LessonDetail } from "@/lib/types";

export type TabId = "lesson" | "test" | "answers";
export type TabTone = "marigold" | "success" | "destructive";
export type LessonTab = { id: TabId; label: string; badge?: { text: string; tone: TabTone } };
export type TabsInput = Pick<LessonDetail, "stage" | "route" | "test_status" | "test_score">;

/** The tabs of a ready lesson, and which one an address (`?tab=`) selects. */
export class LessonTabs {
  static of(lesson: TabsInput): LessonTab[] {
    if (lesson.stage !== "ready") return [];
    const answers: LessonTab = { id: "answers", label: "Quick check answers" };
    if (lesson.route === "mastery") return [{ id: "lesson", label: "Study sheets" }, answers];
    return [{ id: "lesson", label: "Lesson" }, { id: "test", label: "Test", badge: LessonTabs.testBadge(lesson) }, answers];
  }

  /** The tab the address asks for if the lesson has it, else the first one (null when there are no tabs). */
  static pick(tabs: LessonTab[], param: string | null): TabId | null {
    return tabs.find((tab) => tab.id === param)?.id ?? tabs[0]?.id ?? null;
  }

  private static testBadge(lesson: TabsInput): NonNullable<LessonTab["badge"]> {
    switch (lesson.test_status) {
      case "grading":
        return { text: "Grading…", tone: "marigold" };
      case "failed":
        return { text: "Needs another go at grading", tone: "destructive" };
      case "graded": {
        const score = lesson.test_score;
        if (!score || !score.available) return { text: "Final", tone: "success" };
        return { text: `${Math.round((100 * score.awarded) / score.available)}% · final`, tone: "success" };
      }
      default:
        return { text: "1 attempt", tone: "marigold" };
    }
  }
}
