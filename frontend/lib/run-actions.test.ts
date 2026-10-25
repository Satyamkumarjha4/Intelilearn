/**
 * Unit under test: `RunActions`, the console's Retry and Stop on a run, and the words for when they are refused.
 *
 * Why: the console answers a refused action with a 409 and a code, and a staff member who clicks Retry on a lesson
 * that someone else just retried should read "already running", not "request failed". Success must also say what
 * happened, and say which run to look at next.
 *
 * Use cases:
 * - retries a run and says so, with the new run to open
 * - stops a run and says it will stop after the current step
 * - explains each refusal the API makes (wrong stage, a run already going, not retryable, already ended)
 * - explains a run that is gone (404) and a throttled request (429)
 * - uses the API's own message for any other API error, and a generic one for anything else
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { RunActions } from "./run-actions";

const api = (behaviour: { retry?: unknown; cancel?: unknown } = {}) => {
  const calls: string[] = [];
  const settle = (name: string, value: unknown) => async (id: string) => {
    calls.push(`${name} ${id}`);
    if (value instanceof Error) throw value;
    return value;
  };
  const fake = {
    retryRun: settle("retry", behaviour.retry ?? { run_id: "new-run", lesson_id: "lesson-1" }),
    cancelRun: settle("cancel", behaviour.cancel ?? { id: "run-1", status: "cancelled" }),
  };
  return { actions: new RunActions(fake as never), calls };
};

describe("retry and stop", () => {
  test("retries a run and returns the new run to open", async () => {
    const { actions, calls } = api();

    const result = await actions.retry("run-1");

    expect(calls).toEqual(["retry run-1"]);
    expect(result).toEqual({ ok: true, message: "Retry started from the last checkpoint.", runId: "new-run" });
  });

  test("stops a run and says it stops after the current step", async () => {
    const { actions, calls } = api();

    const result = await actions.cancel("run-1");

    expect(calls).toEqual(["cancel run-1"]);
    expect(result).toEqual({ ok: true, message: "The run will stop after its current step.", runId: null });
  });
});

describe("refusals", () => {
  test.each([
    ["wrong_stage", "That lesson has not failed (any more), so there is nothing to retry."],
    ["run_in_progress", "This lesson already has a run going. Give it a moment, then look again."],
    ["not_retryable", "Only a lesson build can be retried. A study sheet, repair or grading run starts again from the lesson."],
    ["run_ended", "This run has already ended."],
  ])("explains a 409 %s", async (code, message) => {
    const { actions } = api({ retry: new ApiError(409, code, "raw"), cancel: new ApiError(409, code, "raw") });

    expect(await actions.retry("r")).toEqual({ ok: false, message });
    expect(await actions.cancel("r")).toEqual({ ok: false, message });
  });

  test("explains a run that is gone", async () => {
    const { actions } = api({ retry: new ApiError(404, "not_found", "Not found.") });

    expect(await actions.retry("r")).toEqual({ ok: false, message: "That run is not there any more. Refresh the list." });
  });

  test("explains a throttled request", async () => {
    const { actions } = api({ cancel: new ApiError(429, "throttled", "Slow down", {}, {}, 12) });

    expect(await actions.cancel("r")).toEqual({ ok: false, message: "Too many requests in a row. Try again in 12 seconds." });
  });

  test("explains a throttled request that does not say how long to wait", async () => {
    const { actions } = api({ cancel: new ApiError(429, "throttled", "Slow down") });

    expect(await actions.cancel("r")).toEqual({ ok: false, message: "Too many requests in a row. Try again in a moment." });
  });

  test("uses the API's own message for any other API error", async () => {
    const { actions } = api({ retry: new ApiError(500, "server_error", "The database is down.") });

    expect(await actions.retry("r")).toEqual({ ok: false, message: "The database is down." });
  });

  test("uses a generic message for anything else", async () => {
    const { actions } = api({ retry: new TypeError("Failed to fetch") });

    expect(await actions.retry("r")).toEqual({ ok: false, message: "That did not work. Check your connection and try again." });
  });
});
