/**
 * Unit under test: `LessonTabs`, the tabs under the journey stepper and the `?tab=` address that selects one.
 *
 * Why: the tabs are linkable, so the address is input from outside. An unknown or stale `?tab=` must fall back to the
 * first tab rather than show nothing, and the Test tab's badge is how a learner sees at a glance whether their one
 * attempt is still to come or is final.
 *
 * Use cases:
 * - a lesson that is not ready has no tabs
 * - a ready lesson has Lesson, Test and Quick check answers; a ready mastery lesson has Study sheets and Quick check
 *   answers
 * - before the test is submitted its tab says "1 attempt"; while grading "Grading…"; when grading failed
 *   "Needs another go at grading"; once graded "<score>% · final" with the rounded percent
 * - the address picks a tab, and an unknown, missing or unavailable tab falls back to the first one
 */
import { describe, expect, test } from "bun:test";

import { LessonTabs, type TabId, type TabsInput } from "./lesson-tabs";

const lesson = (over: Partial<TabsInput> = {}): TabsInput => ({
  stage: "ready",
  route: "lesson",
  test_status: "not_started",
  test_score: null,
  ...over,
});

describe("LessonTabs.of", () => {
  test.each(["preparing_diagnostic", "awaiting_diagnostic", "awaiting_choice", "generating_lesson", "failed"] as const)(
    "a lesson in stage %s has no tabs",
    (stage) => {
      expect(LessonTabs.of(lesson({ stage }))).toEqual([]);
    },
  );

  test("a ready lesson has the lesson, the test and the quick check answers", () => {
    expect(LessonTabs.of(lesson()).map((t) => [t.id, t.label])).toEqual([
      ["lesson", "Lesson"],
      ["test", "Test"],
      ["answers", "Quick check answers"],
    ]);
  });

  test("a ready mastery lesson has the study sheets and the quick check answers", () => {
    expect(LessonTabs.of(lesson({ route: "mastery" })).map((t) => [t.id, t.label])).toEqual([
      ["lesson", "Study sheets"],
      ["answers", "Quick check answers"],
    ]);
  });

  test.each([
    [lesson(), { text: "1 attempt", tone: "marigold" }],
    [lesson({ test_status: "grading" }), { text: "Grading…", tone: "marigold" }],
    [lesson({ test_status: "failed" }), { text: "Needs another go at grading", tone: "destructive" }],
    [lesson({ test_status: "graded", test_score: { awarded: 14, available: 20 } }), { text: "70% · final", tone: "success" }],
    [lesson({ test_status: "graded", test_score: { awarded: 2, available: 3 } }), { text: "67% · final", tone: "success" }],
  ] as const)("the test tab badge follows the test", (input, badge) => {
    expect(LessonTabs.of(input).find((t) => t.id === "test")?.badge).toEqual(badge);
  });

  test("a graded test without a score still says it is final", () => {
    const tabs = LessonTabs.of(lesson({ test_status: "graded", test_score: null }));

    expect(tabs.find((t) => t.id === "test")?.badge).toEqual({ text: "Final", tone: "success" });
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
    ["lesson", "lesson"],
    ["nope", "lesson"],
    ["", "lesson"],
    [null, "lesson"],
  ])("?tab=%s shows %s", (param, shown) => {
    expect(LessonTabs.pick(tabs, param)).toBe(shown);
  });

  test("a tab the lesson does not have falls back to the first one", () => {
    expect(LessonTabs.pick(LessonTabs.of(lesson({ route: "mastery" })), "test")).toBe("lesson");
  });

  test("without tabs there is nothing to pick", () => {
    expect(LessonTabs.pick([], "test")).toBeNull();
  });
});
