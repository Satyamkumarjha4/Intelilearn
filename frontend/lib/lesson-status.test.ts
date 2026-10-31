/**
 * Unit under test: `LessonStatus`, how a lesson in the list is described: its status written as the next action, the
 * link that goes with it, the kind line, the filter chips, how long ago, and which lesson to offer first.
 *
 * Why: the list is the first thing a learner sees. A pill that says "Ready" for a lesson that is waiting for them, or a
 * hero that offers a lesson that is already finished, sends them the wrong way; and a technical word in a pill is noise.
 *
 * Use cases:
 * - every stage has a pill written as what is going on or what to do, with a tone, a spinner while it is being worked
 *   on, and a link text
 * - a ready lesson says whether its test is waiting, being prepared, in progress, being marked, done (with the best
 *   percent) or could not be marked; a ready lesson that is only sheets counts its sheets, in the words of a perfect
 *   quick check when that is how it came about and of a request when the learner asked for them
 * - a ready lesson says "Ready" until all three of its pages have been read here, then "Take the test"; once the test is
 *   marked it says "Test done · best 77%", whatever was read; a retake in progress keeps the best score in view
 * - the kind line is "Lesson · <level>", "Study sheets" (asked for) or "Study sheets · Mastered" (chosen after a perfect
 *   check), or "Quick check" before the route is known, and a lesson made from a test result says which follow-up it is
 * - a lesson with no quick check (a rating, or a follow-up) is never described as preparing one, and one that asked for
 *   sheets is getting its sheets started
 * - a lesson needs the learner when it waits for an answer, or is a ready lesson with a test that is not taken; a lesson
 *   that is only sheets never has a test to take
 * - the filter chips map to stages (several at once), and All to none
 * - times read as just now, minutes, hours, yesterday, days, then a date
 * - the lesson to continue is the most recently updated one that needs the learner, and none if there is none
 */
import { describe, expect, test } from "bun:test";

import { LessonStatus, LESSON_FILTERS } from "./lesson-status";
import type { LessonSummary } from "./types";

const lesson = (over: Partial<LessonSummary> = {}): LessonSummary => ({
  id: "1", topic: "T", stage: "ready", route: "lesson", title: "", level: "beginner", entry: "diagnostic", intent: "lesson", sheets_only: false, followup_level: "", created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z", test_status: "not_started", test_score: null, latest_score: null, best_score: null,
  attempts_count: 0, has_open_attempt: false, material_count: 0, ...over,
});

describe("a lesson with no quick check", () => {
  test.each(["self_rating", "followup"] as const)("%s is not described as preparing a quick check", (entry) => {
    expect(LessonStatus.of(lesson({ stage: "preparing_diagnostic", entry }))).toEqual({
      label: "Getting your lesson started", tone: "primary", spinner: true, action: "Watch",
    });
    expect(LessonStatus.of(lesson({ stage: "preparing_diagnostic", entry: "diagnostic" })).label).toBe("Preparing your quick check");
  });

  test("a rated lesson that asked for sheets is getting its sheets started", () => {
    const rated = lesson({ stage: "preparing_diagnostic", entry: "self_rating", intent: "sheets", sheets_only: true });

    expect(LessonStatus.of(rated)).toEqual({ label: "Getting your sheets started", tone: "primary", spinner: true, action: "Watch" });
    expect(LessonStatus.of({ ...rated, entry: "diagnostic" }).label).toBe("Preparing your quick check");
  });

  test("a follow-up says which kind it is on its kind line, and a plain lesson does not", () => {
    expect(LessonStatus.kind(lesson({ followup_level: "foundation" }))).toBe("Foundation follow-up");
    expect(LessonStatus.kind(lesson({ followup_level: "advanced" }))).toBe("Advanced follow-up");
    expect(LessonStatus.kind(lesson({ followup_level: "" }))).toBe("Lesson · Beginner");
  });
});

describe("pill", () => {
  test.each([
    ["preparing_diagnostic", "Preparing your quick check", "primary", true, "Watch"],
    ["awaiting_diagnostic", "Your quick check is waiting", "marigold", false, "Start"],
    ["awaiting_prerequisite", "A few basics are waiting", "marigold", false, "Start"],
    ["awaiting_choice", "You aced the check · pick a sheet", "insight", false, "Pick a sheet"],
    ["generating_material", "Writing your study sheets", "primary", true, "Watch"],
    ["generating_lesson", "Building your lesson", "primary", true, "Watch"],
    ["failed", "Couldn't finish building", "destructive", false, "Try again"],
  ] as const)("%s", (stage, label, tone, spinner, action) => {
    expect(LessonStatus.of(lesson({ stage }))).toEqual({ label, tone, spinner, action });
  });

  test("a ready lesson says where its test is", () => {
    const of = (test_status: LessonSummary["test_status"], best_score: LessonSummary["best_score"] = null) =>
      LessonStatus.of(lesson({ test_status, best_score, test_score: best_score, latest_score: best_score, attempts_count: best_score ? 1 : 0 }));

    expect(of("not_started")).toEqual({ label: "Ready", tone: "success", spinner: false, action: "Open" });
    expect(of("generating")).toEqual({ label: "Getting your questions ready", tone: "primary", spinner: true, action: "Open" });
    expect(of("in_progress")).toEqual({ label: "Test in progress", tone: "marigold", spinner: false, action: "Open" });
    expect(of("grading")).toEqual({ label: "Marking your test", tone: "primary", spinner: true, action: "Open" });
    expect(of("graded", { awarded: 77, available: 100 })).toEqual({ label: "Test done · best 77%", tone: "success", spinner: false, action: "Open" });
    expect(of("graded", { awarded: 2, available: 3 }).label).toBe("Test done · best 67%");
    expect(of("graded").label).toBe("Test done");
    expect(of("failed")).toEqual({ label: "Test needs marking again", tone: "destructive", spinner: false, action: "Open" });
  });

  test("a retake in progress keeps the best score in view, and says best, not latest", () => {
    const retaking = lesson({ test_status: "in_progress", best_score: { awarded: 16, available: 20 }, latest_score: { awarded: 10, available: 20 }, attempts_count: 2 });

    expect(LessonStatus.of(retaking).label).toBe("Test in progress · best 80%");
    expect(LessonStatus.of({ ...retaking, test_status: "generating" }).label).toBe("Getting your questions ready · best 80%");
  });

  test("the best score is the one shown when the latest attempt was worse", () => {
    const worse = lesson({ test_status: "graded", best_score: { awarded: 18, available: 20 }, latest_score: { awarded: 10, available: 20 }, attempts_count: 2 });

    expect(LessonStatus.of(worse).label).toBe("Test done · best 90%");
  });

  test("a ready lesson says Ready until every page is read, then Take the test", () => {
    const of = (read: number, test_status: LessonSummary["test_status"] = "not_started") => LessonStatus.of(lesson({ test_status }), read);

    expect(of(0).label).toBe("Ready");
    expect(of(2).label).toBe("Ready");
    expect(of(3)).toEqual({ label: "Take the test", tone: "marigold", spinner: false, action: "Take the test" });
    expect(of(7).label).toBe("Take the test"); // read state can hold stale pages; "all of them" is enough
    expect(of(3, "graded").label).toBe("Test done");
    expect(of(3, "grading").label).toBe("Marking your test");
  });

  test("reading pages changes nothing for a lesson that is not a ready lesson with a test", () => {
    expect(LessonStatus.of(lesson({ stage: "generating_lesson" }), 3).label).toBe("Building your lesson");
    expect(LessonStatus.of(lesson({ route: "mastery", sheets_only: true, material_count: 1 }), 3).label).toBe("You aced the check · 1 sheet");
  });

  test("a ready lesson from a perfect check counts its sheets", () => {
    const mastery = { route: "mastery", sheets_only: true } as const;

    expect(LessonStatus.of(lesson({ ...mastery, material_count: 2 }))).toEqual({ label: "You aced the check · 2 sheets", tone: "insight", spinner: false, action: "Open" });
    expect(LessonStatus.of(lesson({ ...mastery, material_count: 1 })).label).toBe("You aced the check · 1 sheet");
    expect(LessonStatus.of(lesson({ ...mastery, material_count: 0 })).label).toBe("You aced the check");
  });

  test("a ready lesson that asked for sheets counts them, with a test nowhere in sight", () => {
    const asked = { route: "", intent: "sheets", sheets_only: true } as const;

    expect(LessonStatus.of(lesson({ ...asked, material_count: 2 }))).toEqual({ label: "2 sheets ready", tone: "success", spinner: false, action: "Open" });
    expect(LessonStatus.of(lesson({ ...asked, material_count: 1 })).label).toBe("1 sheet ready");
    expect(LessonStatus.of(lesson({ ...asked, material_count: 0 })).label).toBe("Ready");
    expect(LessonStatus.of(lesson({ ...asked, material_count: 2 }), 3).label).toBe("2 sheets ready");
  });

  test("no word of the pill is technical", () => {
    const stages = ["preparing_diagnostic", "awaiting_diagnostic", "awaiting_prerequisite", "awaiting_choice", "generating_material", "generating_lesson", "failed", "ready"] as const;

    for (const stage of stages) expect(LessonStatus.of(lesson({ stage })).label).not.toMatch(/diagnostic|stage|node|run\b|graph|model|llm/i);
  });
});

describe("kind line", () => {
  test.each([
    [{ route: "lesson", level: "beginner" }, "Lesson · Beginner"],
    [{ route: "prerequisite", level: "" }, "Lesson"],
    [{ route: "mastery", level: "advanced", sheets_only: true }, "Study sheets · Mastered"],
    [{ route: "", level: "foundation", intent: "sheets", sheets_only: true }, "Study sheets"],
    [{ route: "", level: "", intent: "sheets", sheets_only: true }, "Study sheets"],
    [{ route: "", level: "" }, "Quick check"],
  ] as const)("%j is %s", (over, line) => {
    expect(LessonStatus.kind(lesson(over))).toBe(line);
  });
});

describe("needs the learner", () => {
  test.each([
    [{ stage: "awaiting_diagnostic" }, true],
    [{ stage: "awaiting_prerequisite" }, true],
    [{ stage: "awaiting_choice" }, true],
    [{ stage: "ready" }, true],
    [{ stage: "ready", test_status: "graded" }, false],
    [{ stage: "ready", test_status: "grading" }, false],
    [{ stage: "ready", test_status: "in_progress" }, true],
    [{ stage: "ready", test_status: "generating" }, false],
    [{ stage: "ready", route: "mastery", sheets_only: true }, false],
    [{ stage: "ready", route: "", intent: "sheets", sheets_only: true }, false],
    [{ stage: "generating_lesson" }, false],
    [{ stage: "failed" }, false],
  ] as const)("%j is %s", (over, needs) => {
    expect(LessonStatus.needsLearner(lesson(over))).toBe(needs);
  });
});

describe("filters", () => {
  test("map chips to stages, and All to none", () => {
    const stages = Object.fromEntries(LESSON_FILTERS.map((f) => [f.label, f.stages]));

    expect(stages["All"]).toEqual([]);
    expect(stages["Needs you"]).toEqual(["awaiting_diagnostic", "awaiting_prerequisite", "awaiting_choice"]);
    expect(stages["Building"]).toEqual(["preparing_diagnostic", "generating_material", "generating_lesson"]);
    expect(stages["Ready"]).toEqual(["ready"]);
    expect(stages["Couldn't finish"]).toEqual(["failed"]);
  });
});

describe("ago", () => {
  const now = Date.parse("2026-10-25T12:00:00Z");
  test.each([
    ["2026-10-25T11:59:40Z", "just now"],
    ["2026-10-25T11:55:00Z", "5 min ago"],
    ["2026-10-25T11:00:00Z", "1 hour ago"],
    ["2026-10-25T07:00:00Z", "5 hours ago"],
    ["2026-10-24T09:00:00Z", "yesterday"],
    ["2026-10-22T12:00:00Z", "3 days ago"],
    ["2026-09-01T12:00:00Z", "Sep 1, 2026"],
    ["2026-10-25T13:00:00Z", "just now"],
    ["nonsense", ""],
  ])("%s reads %s", (iso, text) => {
    expect(LessonStatus.ago(iso, now, "en-US")).toBe(text);
  });
});

describe("pickContinue", () => {
  test("is the most recently updated lesson that needs the learner", () => {
    const old = lesson({ id: "a", stage: "awaiting_diagnostic", updated_at: "2026-10-20T10:00:00Z" });
    const recent = lesson({ id: "b", stage: "ready", updated_at: "2026-10-24T10:00:00Z" });
    const done = lesson({ id: "c", stage: "ready", test_status: "graded", updated_at: "2026-10-25T10:00:00Z" });

    expect(LessonStatus.pickContinue([old, done, recent])?.id).toBe("b");
  });

  test("is nothing when no lesson needs the learner", () => {
    expect(LessonStatus.pickContinue([lesson({ stage: "failed" }), lesson({ test_status: "graded" })])).toBeNull();
    expect(LessonStatus.pickContinue([])).toBeNull();
  });
});
