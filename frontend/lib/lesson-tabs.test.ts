/**
 * Unit under test: `LessonTabs`, the tabs under the journey stepper and the `?tab=` address that selects one.
 *
 * Why: the tabs are linkable, so the address is input from outside. An unknown or stale `?tab=` must fall back to the
 * first tab rather than show nothing, and the Test tab's badge is how a learner sees at a glance whether their one
 * attempt is still to come or is final.
 *
 * Use cases:
 * - a lesson that is not ready has no tabs
 * - a learner who rated themselves took no quick check, so their lesson has no Quick check answers tab, whatever it is
 * - a ready lesson has Lesson, Test, Study sheets (any ready lesson can have sheets made for it) and Quick check
 *   answers; a lesson that is only study sheets (asked for, or chosen after a perfect check) has just Study sheets and
 *   Quick check answers, with no lesson and no test to show
 * - before the test is taken its tab says "To do"; while its questions are being written "Getting ready…"; while it is
 *   being taken "In progress"; while grading "Grading…"; when grading failed "Needs another go at grading"; once graded
 *   "<latest score>% · attempt <n>" with the rounded percent
 * - a retake in progress keeps the score of the last attempt: "<score>% · trying again"
 * - the address picks a tab, and an unknown, missing or unavailable tab falls back to the first one
 */
import { describe, expect, test } from "bun:test";

import { LessonTabs, type TabId, type TabsInput } from "./lesson-tabs";

const lesson = (over: Partial<TabsInput> = {}): TabsInput => ({
  stage: "ready",
  sheets_only: false,
  test_status: "not_started",
  latest_score: null,
  attempts_count: 0,
  entry: "diagnostic",
  ...over,
});

describe("LessonTabs.of", () => {
  test.each(["preparing_diagnostic", "awaiting_diagnostic", "awaiting_choice", "generating_lesson", "failed"] as const)(
    "a lesson in stage %s has no tabs",
    (stage) => {
      expect(LessonTabs.of(lesson({ stage }))).toEqual([]);
    },
  );

  test("a ready lesson has the lesson, the test, the study sheets and the quick check answers", () => {
    expect(LessonTabs.of(lesson()).map((t) => [t.id, t.label])).toEqual([
      ["lesson", "Lesson"],
      ["test", "Test"],
      ["sheets", "Study sheets"],
      ["answers", "Quick check answers"],
    ]);
  });

  test("a self-rated lesson has no quick check answers", () => {
    expect(LessonTabs.of(lesson({ entry: "self_rating" })).map((t) => t.id)).toEqual(["lesson", "test", "sheets"]);
    expect(LessonTabs.of(lesson({ entry: "self_rating", sheets_only: true })).map((t) => t.id)).toEqual(["sheets"]);
  });

  test("a lesson that is only study sheets has the sheets and the quick check answers, and no lesson or test", () => {
    expect(LessonTabs.of(lesson({ sheets_only: true })).map((t) => [t.id, t.label])).toEqual([
      ["sheets", "Study sheets"],
      ["answers", "Quick check answers"],
    ]);
  });

  test.each([
    [lesson(), { text: "To do", tone: "marigold" }],
    [lesson({ test_status: "generating" }), { text: "Getting ready…", tone: "marigold" }],
    [lesson({ test_status: "in_progress" }), { text: "In progress", tone: "marigold" }],
    [lesson({ test_status: "grading" }), { text: "Grading…", tone: "marigold" }],
    [lesson({ test_status: "failed" }), { text: "Needs another go at grading", tone: "destructive" }],
    [lesson({ test_status: "graded", attempts_count: 1, latest_score: { awarded: 14, available: 20 } }), { text: "70% · attempt 1", tone: "success" }],
    [lesson({ test_status: "graded", attempts_count: 3, latest_score: { awarded: 2, available: 3 } }), { text: "67% · attempt 3", tone: "success" }],
    [lesson({ test_status: "in_progress", attempts_count: 1, latest_score: { awarded: 14, available: 20 } }), { text: "70% · trying again", tone: "marigold" }],
    [lesson({ test_status: "generating", attempts_count: 2, latest_score: { awarded: 18, available: 20 } }), { text: "90% · trying again", tone: "marigold" }],
  ] as const)("the test tab badge follows the test", (input, badge) => {
    expect(LessonTabs.of(input).find((t) => t.id === "test")?.badge).toEqual(badge);
  });

  test("a graded test without a score says how many attempts there have been", () => {
    const tabs = LessonTabs.of(lesson({ test_status: "graded", latest_score: null, attempts_count: 2 }));

    expect(tabs.find((t) => t.id === "test")?.badge).toEqual({ text: "Attempt 2", tone: "success" });
  });

  test("a lesson that is only sheets has no test badge to show", () => {
    expect(LessonTabs.of(lesson({ sheets_only: true })).some((t) => t.badge)).toBe(false);
  });

  test("the other tabs have no badge", () => {
    expect(LessonTabs.of(lesson()).filter((t) => t.badge).map((t) => t.id)).toEqual(["test"]);
  });
});

describe("LessonTabs.pick", () => {
  const tabs = LessonTabs.of(lesson());

  test.each<[string | null, TabId]>([
    ["test", "test"],
    ["answers", "answers"],
    ["sheets", "sheets"],
    ["lesson", "lesson"],
    ["nope", "lesson"],
    ["", "lesson"],
    [null, "lesson"],
  ])("?tab=%s shows %s", (param, shown) => {
    expect(LessonTabs.pick(tabs, param)).toBe(shown);
  });

  test("a tab the lesson does not have falls back to the first one", () => {
    expect(LessonTabs.pick(LessonTabs.of(lesson({ sheets_only: true })), "test")).toBe("sheets");
    expect(LessonTabs.pick(LessonTabs.of(lesson({ sheets_only: true })), "lesson")).toBe("sheets"); // an old link
  });

  test("without tabs there is nothing to pick", () => {
    expect(LessonTabs.pick([], "test")).toBeNull();
  });
});
