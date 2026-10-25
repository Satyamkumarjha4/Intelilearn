/**
 * Unit under test: `Journey`, which turns a lesson into the steps of the journey stepper at the top of the workspace.
 *
 * Why: the stepper is how a learner knows where they are. A step stuck on "now" after the lesson moved on, a "Your
 * level" step that is ticked before the level is known, or a failure shown on the wrong step each make a working
 * lesson look broken.
 *
 * Use cases:
 * - the lesson route is Diagnose, Your level, Learn, Test, Revisit; the mastery route is Diagnose, Mastered,
 *   Pick a sheet, Study; a lesson whose route is not known yet shows the lesson route
 * - while the quizzes are prepared or answered, Diagnose is the current step
 * - while the lesson is built, Diagnose is done, Your level is done once the assessment exists (else current), and
 *   Learn is current
 * - a ready lesson is on Learn until the test is submitted; once it is graded or being graded, Test is done and
 *   Revisit is current; a test that could not be graded keeps Test current
 * - the mastery route waits on Pick a sheet, then Study is current while the sheet is written and once it is ready
 * - a failed lesson keeps the step it failed on as current with the failed flag: Diagnose before the quiz was
 *   answered, Your level after, Learn once the assessment exists, Study on the mastery route
 * - a failed lesson that is being retried is not shown as failed
 * - the tag next to the title is the level once known (assessment first), else the route, else nothing
 */
import { describe, expect, test } from "bun:test";

import { Journey, type JourneyInput } from "./journey";

const lesson = (over: Partial<JourneyInput> = {}): JourneyInput => ({
  stage: "preparing_diagnostic",
  route: "",
  assessment: null,
  results: { diagnostic: null, prerequisite: null },
  test_status: "not_started",
  active_run_id: null,
  ...over,
});
const assessment = { level: "beginner", known_concepts: [], gaps: [], start_point: "", confidence: "high" };
const answered = { correct: 5, total: 10, dont_know: 0, by_band: {} };
const states = (input: JourneyInput) => Journey.of(input).map((step) => `${step.label}:${step.state}${step.failed ? "!" : ""}`);

describe("Journey.of", () => {
  test("names the steps of each route", () => {
    expect(Journey.of(lesson()).map((s) => s.label)).toEqual(["Diagnose", "Your level", "Learn", "Test", "Revisit"]);
    expect(Journey.of(lesson({ route: "prerequisite" })).map((s) => s.label)).toHaveLength(5);
    expect(Journey.of(lesson({ route: "mastery", stage: "awaiting_choice" })).map((s) => s.label)).toEqual([
      "Diagnose", "Mastered", "Pick a sheet", "Study",
    ]);
  });

  test.each(["preparing_diagnostic", "awaiting_diagnostic", "awaiting_prerequisite"] as const)(
    "while %s, Diagnose is the current step",
    (stage) => {
      expect(states(lesson({ stage }))).toEqual(["Diagnose:now", "Your level:todo", "Learn:todo", "Test:todo", "Revisit:todo"]);
    },
  );

  test("while the lesson is built, Diagnose and Your level are done once the assessment exists", () => {
    const built = lesson({ stage: "generating_lesson", route: "lesson", assessment, results: { diagnostic: answered, prerequisite: null } });

    expect(states(built)).toEqual(["Diagnose:done", "Your level:done", "Learn:now", "Test:todo", "Revisit:todo"]);
  });

  test("while the level is still being worked out, Your level is the current step", () => {
    const working = lesson({ stage: "generating_lesson", results: { diagnostic: answered, prerequisite: null } });

    expect(states(working)).toEqual(["Diagnose:done", "Your level:now", "Learn:todo", "Test:todo", "Revisit:todo"]);
  });

  test("a ready lesson is on Learn until the test is taken", () => {
    const ready = lesson({ stage: "ready", route: "lesson", assessment, test_status: "not_started" });

    expect(states(ready)).toEqual(["Diagnose:done", "Your level:done", "Learn:now", "Test:todo", "Revisit:todo"]);
  });

  test.each(["grading", "graded"] as const)("a test that is %s makes Test done and Revisit current", (test_status) => {
    expect(states(lesson({ stage: "ready", route: "lesson", assessment, test_status }))).toEqual([
      "Diagnose:done", "Your level:done", "Learn:done", "Test:done", "Revisit:now",
    ]);
  });

  test("a test that could not be graded keeps Test current", () => {
    expect(states(lesson({ stage: "ready", route: "lesson", assessment, test_status: "failed" }))).toEqual([
      "Diagnose:done", "Your level:done", "Learn:done", "Test:now", "Revisit:todo",
    ]);
  });

  test("the mastery route waits on Pick a sheet, then Study is current", () => {
    const base = { route: "mastery" as const, results: { diagnostic: answered, prerequisite: null } };

    expect(states(lesson({ ...base, stage: "awaiting_choice" }))).toEqual([
      "Diagnose:done", "Mastered:done", "Pick a sheet:now", "Study:todo",
    ]);
    for (const stage of ["generating_material", "ready"] as const) {
      expect(states(lesson({ ...base, stage }))).toEqual(["Diagnose:done", "Mastered:done", "Pick a sheet:done", "Study:now"]);
    }
  });

  test.each([
    ["before the quiz was answered", {}, "Diagnose"],
    ["after the quiz, before the assessment", { results: { diagnostic: answered, prerequisite: null } }, "Your level"],
    ["once the assessment exists", { assessment, results: { diagnostic: answered, prerequisite: null } }, "Learn"],
  ] as const)("a lesson that failed %s keeps that step current and failed", (_, over, label) => {
    const steps = Journey.of(lesson({ stage: "failed", ...over }));

    const current = steps.filter((step) => step.state === "now");
    expect(current.map((s) => s.label)).toEqual([label]);
    expect(current[0].failed).toBe(true);
    expect(steps.filter((s) => s.failed)).toHaveLength(1);
    expect(steps.slice(0, steps.indexOf(current[0])).every((s) => s.state === "done")).toBe(true);
    expect(steps.slice(steps.indexOf(current[0]) + 1).every((s) => s.state === "todo")).toBe(true);
  });

  test("a mastery lesson that failed fails on Study", () => {
    const steps = Journey.of(lesson({ stage: "failed", route: "mastery", results: { diagnostic: answered, prerequisite: null } }));

    expect(steps.map((s) => `${s.label}:${s.state}${s.failed ? "!" : ""}`)).toEqual([
      "Diagnose:done", "Mastered:done", "Pick a sheet:done", "Study:now!",
    ]);
  });

  test("a failed lesson that is being retried is not shown as failed", () => {
    const steps = Journey.of(lesson({ stage: "failed", assessment, active_run_id: "r1", results: { diagnostic: answered, prerequisite: null } }));

    expect(steps.some((s) => s.failed)).toBe(false);
    expect(steps.find((s) => s.state === "now")?.label).toBe("Learn");
  });
});

describe("Journey.tag", () => {
  test.each([
    [{ route: "lesson", level: "", assessment: null }, "Lesson"],
    [{ route: "mastery", level: "", assessment: null }, "Mastery"],
    [{ route: "prerequisite", level: "", assessment: null }, "Foundations first"],
    [{ route: "", level: "", assessment: null }, null],
    [{ route: "lesson", level: "advanced", assessment: null }, "Advanced level"],
    [{ route: "lesson", level: "advanced", assessment: assessment }, "Beginner level"],
    [{ route: "lesson", level: "", assessment: { ...assessment, level: "INTERMEDIATE" } }, "Intermediate level"],
  ] as const)("%j reads %s", (input, tag) => {
    expect(Journey.tag(input as Parameters<typeof Journey.tag>[0])).toBe(tag);
  });
});
