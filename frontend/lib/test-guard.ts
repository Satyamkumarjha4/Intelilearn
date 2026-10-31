import type { TabId } from "@/lib/lesson-tabs";
import type { LessonDetail } from "@/lib/types";

/**
 * While a learner is in the middle of the test, the lesson's pages and its study sheets are closed: a test that can be
 * answered with the lesson open in the next tab measures nothing. The test itself stays open, and so do the quick check
 * answers. This is a courtesy of the screen, not a security rule: the content is still the learner's own, and the server
 * serves it as before.
 */
export class TestGuard {
  /** The tabs that are closed while an attempt is in progress. */
  static readonly CLOSED: readonly TabId[] = ["lesson", "sheets"];

  static readonly TITLE = "Finish your test first";
  static readonly TEXT = "You're partway through a test. Finish it, and the lesson and your study sheets will be here for you.";
  static readonly BUTTON = "Back to my test";

  static blocks(tab: TabId, lesson: Pick<LessonDetail, "test_status">): boolean {
    return TestGuard.CLOSED.includes(tab) && lesson.test_status === "in_progress";
  }
}
