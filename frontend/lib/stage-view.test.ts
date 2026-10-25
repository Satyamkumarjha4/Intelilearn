/**
 * Unit under test: `StageView`, which decides which screen the lesson page shows and what to say after a score.
 *
 * Why: the page must never offer a quiz that cannot be answered, show a stale error right after Retry, or leave
 * the learner on a spinner when it is their turn.
 *
 * Use cases:
 * - each waiting stage shows its quiz or the choice screen
 * - working stages show progress
 * - a failed lesson shows the error, except while a retry is running
 * - a ready lesson shows the study sheets for mastery and the lesson otherwise
 * - a run still active when the lesson is waiting for a quiz does not hide the quiz
 * - the next-step sentence follows the route
 * - band scores come back easiest first whatever order the API's JSON had, and bands that were not asked are left out
 */
import { describe, expect, test } from "bun:test";

import { StageView } from "./stage-view";
import type { LessonDetail } from "./types";

const lesson = (stage: LessonDetail["stage"], extra: Partial<LessonDetail> = {}) => ({
  stage,
  route: "" as LessonDetail["route"],
  active_run_id: null,
  ...extra,
});

describe("StageView.of", () => {
  test.each([
    ["awaiting_diagnostic", "diagnostic"],
    ["awaiting_prerequisite", "prerequisite"],
    ["awaiting_choice", "choice"],
    ["preparing_diagnostic", "progress"],
    ["generating_material", "progress"],
    ["generating_lesson", "progress"],
    ["failed", "failed"],
  ] as const)("%s shows %s", (stage, screen) => {
    expect(StageView.of(lesson(stage))).toBe(screen);
  });

  test("a failed lesson shows progress while a retry runs", () => {
    expect(StageView.of(lesson("failed", { active_run_id: "r1" }))).toBe("progress");
  });

  test("a ready lesson shows study sheets for mastery and the lesson otherwise", () => {
    expect(StageView.of(lesson("ready", { route: "mastery" }))).toBe("material");
    expect(StageView.of(lesson("ready", { route: "lesson" }))).toBe("lesson");
    expect(StageView.of(lesson("ready", { route: "prerequisite" }))).toBe("lesson");
  });

  test("a run that is still finishing does not hide the quiz the lesson is waiting for", () => {
    expect(StageView.of(lesson("awaiting_diagnostic", { active_run_id: "r1" }))).toBe("diagnostic");
    expect(StageView.of(lesson("awaiting_prerequisite", { active_run_id: "r1" }))).toBe("prerequisite");
    expect(StageView.of(lesson("awaiting_choice", { active_run_id: "r1" }))).toBe("choice");
  });

  test("a working stage with an active run shows progress", () => {
    expect(StageView.of(lesson("generating_lesson", { active_run_id: "r1" }))).toBe("progress");
  });
});

describe("StageView.nextStep", () => {
  test("follows the route", () => {
    expect(StageView.nextStep("prerequisite")).toBe("We'll check a few foundations first.");
    expect(StageView.nextStep("mastery")).toContain("already know this well");
    expect(StageView.nextStep("lesson", "intermediate")).toBe("Building your lesson at intermediate level.");
    expect(StageView.nextStep("lesson")).toBe("Building your lesson.");
    expect(StageView.nextStep(undefined)).toBe("");
  });
});

describe("StageView.bandsOf", () => {
  test("orders the bands easiest first and skips the ones that were not asked", () => {
    const result = { correct: 1, total: 3, dont_know: 0, by_band: { hard: [0, 1], basic: [1, 1], moderate: [0, 1] } };

    expect(StageView.bandsOf(result as never)).toEqual([
      ["basic", [1, 1]],
      ["moderate", [0, 1]],
      ["hard", [0, 1]],
    ]);
  });

  test("a prerequisite quiz has no bands", () => {
    expect(StageView.bandsOf({ correct: 3, total: 5, dont_know: 0, by_band: {} })).toEqual([]);
  });
});
