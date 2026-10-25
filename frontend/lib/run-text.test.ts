/**
 * Unit under test: `RunText`, the words and numbers the console's run list and detail panel show.
 *
 * Why: staff scan a table of runs for the odd one out. Times, costs and statuses written inconsistently (a cost of
 * $0.000 for a sixth of a cent, "Running" for a run that is only waiting for the learner) hide the very thing the
 * table exists to show.
 *
 * Use cases:
 * - writes a duration as seconds, minutes or hours, and "—" when there is none
 * - writes a cost with more places while it is under a cent, so a cheap run is not shown as free
 * - shortens a run id and names the job (lesson flow, study sheet, repair, grading)
 * - gives each run status a label and a tone (a paused run reads "Waiting for learner")
 * - gives a model call's result a label and a tone (worked, worked on a retry, invalid output, failed)
 * - describes where the lesson is in words, and what it does not know yet as it is
 * - writes how long ago a run started, and its exact time for the hover title
 */
import { describe, expect, test } from "bun:test";

import { RunText } from "./run-text";

describe("duration", () => {
  test.each([
    [null, "—"],
    [0, "0 s"],
    [2.44, "2.4 s"],
    [9.96, "10 s"],
    [41, "41 s"],
    [59.6, "1 m 00 s"],
    [252, "4 m 12 s"],
    [363, "6 m 03 s"],
    [3900, "1 h 05 m"],
  ])("%p is written %p", (seconds, text) => {
    expect(RunText.duration(seconds)).toBe(text);
  });
});

describe("cost", () => {
  test.each([
    ["0.000000", "$0.000"],
    ["0.004000", "$0.004"],
    ["0.009600", "$0.010"],
    ["0.140000", "$0.14"],
    ["12.500000", "$12.50"],
  ])("%p is written %p", (money, text) => {
    expect(RunText.cost(money)).toBe(text);
  });

  test("writes a missing cost as a dash", () => {
    expect(RunText.cost(null)).toBe("—");
  });
});

describe("ids and jobs", () => {
  test("shortens a run id to its first eight characters", () => {
    expect(RunText.shortId("7f3a9c10-2b44-4a8e-9d11-0e5b7c1d2f33")).toBe("7f3a9c10");
  });

  test.each([
    ["flow", "Lesson flow"],
    ["study_material", "Study sheet"],
    ["runtime_repair", "Repair"],
    ["grade_test", "Grading"],
  ] as const)("names the %s job %p", (graph, name) => {
    expect(RunText.job(graph)).toBe(name);
  });
});

describe("status", () => {
  test.each([
    ["queued", "Queued", "off"],
    ["running", "Running", "run"],
    ["paused", "Waiting for learner", "wait"],
    ["succeeded", "Finished", "ok"],
    ["failed", "Failed", "bad"],
    ["cancelled", "Stopped", "off"],
  ] as const)("%s reads %p with the %s tone", (status, label, tone) => {
    expect(RunText.status(status)).toEqual({ label, tone });
  });

  test("only a queued or running run is still moving", () => {
    expect(["queued", "running", "paused", "succeeded", "failed", "cancelled"].filter((s) => RunText.isActive(s as never))).toEqual([
      "queued",
      "running",
    ]);
  });
});

describe("model call result", () => {
  test.each([
    ["ok", "ok", "ok", "ok"],
    ["retried", "ok", "retried", "wait"],
    ["failed", "invalid_output", "invalid", "bad"],
    ["failed", "fatal_error", "failed", "bad"],
    ["failed", "retryable_error", "failed", "bad"],
  ] as const)("outcome %s with status %s reads %p", (outcome, status, label, tone) => {
    expect(RunText.callResult({ outcome, status })).toEqual({ label, tone });
  });
});

describe("stage", () => {
  test.each([
    ["preparing_diagnostic", "Preparing quick check"],
    ["awaiting_diagnostic", "Waiting for quick check"],
    ["awaiting_prerequisite", "Waiting for foundations check"],
    ["awaiting_choice", "Waiting for sheet choice"],
    ["generating_material", "Writing study sheet"],
    ["generating_lesson", "Building lesson"],
    ["ready", "Ready"],
    ["failed", "Failed"],
  ] as const)("%s reads %p", (stage, text) => {
    expect(RunText.stage(stage)).toBe(text);
  });

  test("shows a stage it does not know as it is, with spaces for underscores", () => {
    expect(RunText.stage("brand_new_stage" as never)).toBe("brand new stage");
  });
});

describe("times", () => {
  const now = new Date("2026-10-25T12:00:00Z");

  test.each([
    ["2026-10-25T11:59:40Z", "just now"],
    ["2026-10-25T11:48:00Z", "12 min ago"],
    ["2026-10-25T09:00:00Z", "3 h ago"],
    ["2026-10-23T12:00:00Z", "2 d ago"],
    ["2026-10-25T12:00:30Z", "just now"],
  ])("%s reads %p", (iso, text) => {
    expect(RunText.ago(iso, now)).toBe(text);
  });

  test("falls back to the date for a run older than a month", () => {
    expect(RunText.ago("2026-08-01T12:00:00Z", now, "en-GB", "UTC")).toBe("1 Aug 2026");
  });

  test("writes nothing for a time that is not one", () => {
    expect(RunText.ago("nope", now)).toBe("");
    expect(RunText.exact("nope")).toBe("");
  });

  test("writes the exact time for the hover title", () => {
    expect(RunText.exact("2026-10-25T11:48:09Z", "en-GB", "UTC")).toBe("25 Oct 2026, 11:48:09");
  });
});
