/**
 * Unit under test: `AttemptErrors`, `AttemptPreparation`, `AnswerLocker` and `AttemptSubmitFlow`, how a learner opens an
 * attempt, answers it a card at a time and hands it in.
 *
 * Why: the server owns the attempt, so what the browser does around it must survive what a real network does. A retake
 * has to wait for its questions and say so; a run that fails leaves no attempt, which has to read as "try again" rather
 * than a spinner for ever; an answer that was already saved (a double click) must not look like a failure; leaving the
 * page must stop following a run; and an attempt handed in twice is simply read.
 *
 * Use cases:
 * - the first attempt is ready at once and the questions are read; nothing is announced as preparing
 * - a retake announces that it is preparing, follows its run to the end, and is ready when the attempt has its questions
 * - a retake whose run failed (no open attempt afterwards) is reported as failed, and so is one the page left
 * - the learner can stop the wait: the run is stopped, following ends, the wait is reported as cancelled (not failed) and the
 *   attempt is not read; if the run had already ended by itself the stop is a no-op and the questions are found; any other
 *   error from the stop is passed on; there is nothing to stop before a run is known, when only polling, or twice
 * - a repeated start of a retake with no run to follow asks now and then until the questions are there
 * - an answer is saved on the server; one the server already has counts as saved; a sealed attempt and a network
 *   failure are reported with words for the learner
 * - a refused start or save is told in words: the day's retakes are used up, the learner is going too fast, or the
 *   action was refused in the server's own words
 * - handing in: a lesson attempt comes back graded and no run is followed; a legacy attempt is shown at once, followed to
 *   the end of its run and read again; an attempt that is already over is read; other errors reject; leaving the page
 *   stops following and silences updates
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { AnswerLocker, AttemptErrors, AttemptPreparation, AttemptSubmitFlow } from "./attempt-flow";
import type { AttemptStarted, LearnerTest, TestSubmission } from "./types";

const started = (over: Partial<AttemptStarted> = {}): AttemptStarted => ({
  attempt_id: "A1", attempt_no: 1, status: "in_progress", run_id: null, questions: [], total_marks: 20, answers: {}, started_at: "2026-10-30T10:00:00Z", ...over,
});
const test_ = (status: "generating" | "in_progress" | null): LearnerTest => ({
  questions: [], total_marks: 20, answers: {}, next_attempt_no: 2, submission: null,
  attempt: status ? { id: "A1", attempt_no: 2, status, started_at: "2026-10-30T10:00:00Z", submitted_at: null } : null,
});
const attempt = (over: Partial<TestSubmission> = {}): TestSubmission => ({
  id: "A1", attempt_no: 1, status: "graded", error: "", questions: [], answers: {}, result: null, revisit_links: [], awarded: 14, available: 20, band: "normal",
  duration_s: 60, followup: null, started_at: "2026-10-30T10:00:00Z", submitted_at: "2026-10-30T10:01:00Z", graded_at: "2026-10-30T10:01:00Z", ...over,
});

function follower() {
  const followed: { runId: string; end: () => void; stopped: boolean }[] = [];
  const follow = (runId: string, end: () => void) => {
    const entry = { runId, end, stopped: false };
    followed.push(entry);
    return () => {
      entry.stopped = true;
    };
  };
  return { followed, follow };
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("AttemptErrors", () => {
  test("recognises a question that is already locked and an attempt that is already over", () => {
    expect(AttemptErrors.locked(new ApiError(409, "locked", "x"))).toBe(true);
    expect(AttemptErrors.locked(new ApiError(409, "attempt_sealed", "x"))).toBe(false);
    expect(AttemptErrors.sealed(new ApiError(409, "attempt_sealed", "x"))).toBe(true);
    expect(AttemptErrors.sealed(new ApiError(400, "attempt_sealed", "x"))).toBe(false);
    expect(AttemptErrors.sealed(new Error("boom"))).toBe(false);
    expect(AttemptErrors.locked(undefined)).toBe(false);
  });

  test.each([
    [new ApiError(429, "retake_limit", "server words"), "That's enough tries for today. You can try again tomorrow."],
    [new ApiError(429, "throttled", "server words"), "You're going a bit fast. Wait a moment and try again."],
    [new ApiError(409, "wrong_stage", "The lesson is not ready."), "The lesson is not ready."],
    [new ApiError(403, "out_of_credits", "You have used all your tries for today."), "You have used all your tries for today."],
    [new Error("boom"), "fallback words"],
  ])("tells a refusal in words for the learner", (error, words) => {
    expect(AttemptErrors.message(error, "fallback words")).toBe(words);
  });
});

describe("AttemptPreparation", () => {
  const stops: string[] = [];
  const api = (start: AttemptStarted, reads: LearnerTest[], cancel: (runId: string) => Promise<void> = async (runId) => void stops.push(runId)) => ({
    startAttempt: async () => start,
    test: async () => reads.shift() ?? reads[0] ?? test_(null),
    cancelRun: cancel,
  });

  test("the first attempt is ready at once and nothing is announced", async () => {
    const { follow, followed } = follower();
    const announced: string[] = [];

    const result = await new AttemptPreparation(api(started(), [test_("in_progress")]), follow).run("L1", () => announced.push("preparing"));

    expect(result.kind).toBe("ready");
    expect(announced).toEqual([]);
    expect(followed).toHaveLength(0);
  });

  test("a retake announces that it is preparing, follows its run and is ready when the attempt has its questions", async () => {
    const { follow, followed } = follower();
    const announced: string[] = [];
    const flow = new AttemptPreparation(api(started({ status: "generating", run_id: "R1", attempt_no: 2 }), [test_("in_progress")]), follow);

    const done = flow.run("L1", () => announced.push("preparing"));
    await tick();
    expect(announced).toEqual(["preparing"]);
    expect(followed.map((f) => f.runId)).toEqual(["R1"]);
    followed[0].end();

    expect((await done).kind).toBe("ready");
  });

  test("a retake whose run failed leaves no attempt, which is reported as failed", async () => {
    const { follow, followed } = follower();
    const flow = new AttemptPreparation(api(started({ status: "generating", run_id: "R1" }), [test_(null)]), follow);

    const done = flow.run("L1", () => {});
    await tick();
    followed[0].end();

    expect(await done).toEqual({ kind: "failed" });
  });

  describe("stopping the wait", () => {
    const retake = () => started({ status: "generating", run_id: "R1", attempt_no: 2 });

    test("stops the run, ends the wait as cancelled and never reads the attempt", async () => {
      stops.length = 0;
      const { follow, followed } = follower();
      let reads = 0;
      const flow = new AttemptPreparation({ ...api(retake(), [test_("in_progress")]), test: async () => (reads++, test_("in_progress")) }, follow);
      const done = flow.run("L1", () => {});
      await tick();

      expect(flow.cancellable).toBe(true);
      expect(await flow.cancel()).toBe(true);

      expect(await done).toEqual({ kind: "cancelled" });
      expect(stops).toEqual(["R1"]);
      expect(followed[0].stopped).toBe(true);
      expect(reads).toBe(0);
      expect(flow.cancellable).toBe(false);
      expect(await flow.cancel()).toBe(false);
    });

    test("a run that had already ended is not stopped, and the questions are found", async () => {
      const { follow, followed } = follower();
      const ended = async () => {
        throw new ApiError(409, "run_ended", "That run has already ended.");
      };
      const flow = new AttemptPreparation(api(retake(), [test_("in_progress")], ended), follow);
      const done = flow.run("L1", () => {});
      await tick();

      expect(await flow.cancel()).toBe(false);
      followed[0].end();

      expect((await done).kind).toBe("ready");
    });

    test("any other error from the stop is passed on, and the wait goes on", async () => {
      const { follow, followed } = follower();
      const broken = async () => {
        throw new ApiError(500, "error", "boom");
      };
      const flow = new AttemptPreparation(api(retake(), [test_("in_progress")], broken), follow);
      const done = flow.run("L1", () => {});
      await tick();

      await expect(flow.cancel()).rejects.toThrow("boom");
      expect(flow.cancellable).toBe(true);
      followed[0].end();
      expect((await done).kind).toBe("ready");
    });

    test("there is nothing to stop before a run is known, or when the wait is only polling", async () => {
      const { follow } = follower();
      const polling = new AttemptPreparation(api(started({ status: "generating", run_id: null }), [test_("generating"), test_("in_progress"), test_("in_progress")]), follow, async () => {});
      expect(polling.cancellable).toBe(false);
      const done = polling.run("L1", () => {});
      await tick();

      expect(polling.cancellable).toBe(false);
      expect(await polling.cancel()).toBe(false);
      await done;
    });
  });

  test("leaving the page stops following the run and reports nothing ready", async () => {
    const { follow, followed } = follower();
    const flow = new AttemptPreparation(api(started({ status: "generating", run_id: "R1" }), [test_("in_progress")]), follow);

    const done = flow.run("L1", () => {});
    await tick();
    flow.dispose();
    followed[0].end();

    expect(await done).toEqual({ kind: "failed" });
    expect(followed[0].stopped).toBe(true);
  });

  test("a start with no run to follow asks now and then until the questions are there", async () => {
    const { follow } = follower();
    const pauses: number[] = [];
    const reads = [test_("generating"), test_("generating"), test_("in_progress"), test_("in_progress")];
    const flow = new AttemptPreparation(api(started({ status: "generating", run_id: null }), reads), follow, async (ms) => void pauses.push(ms));

    const result = await flow.run("L1", () => {});

    expect(result.kind).toBe("ready");
    expect(pauses).toEqual([2000, 2000]);
  });

  test("a start that is refused rejects with the server's error", async () => {
    const flow = new AttemptPreparation(
      { startAttempt: async () => Promise.reject(new ApiError(429, "retake_limit", "x")), test: async () => test_(null), cancelRun: async () => {} },
      () => () => {},
    );

    await expect(flow.run("L1", () => {})).rejects.toThrow("x");
  });
});

describe("AnswerLocker", () => {
  test("saves the answer on the server, locking the question", async () => {
    const calls: unknown[][] = [];
    const locker = new AnswerLocker({ saveAnswer: async (...args) => void calls.push(args) as never });

    expect(await locker.lock("L1", "A1", "t1", [0, 2])).toEqual({ ok: true });
    expect(calls).toEqual([["L1", "A1", "t1", [0, 2]]]);
  });

  test("an answer the server already has counts as saved", async () => {
    const locker = new AnswerLocker({ saveAnswer: async () => Promise.reject(new ApiError(409, "locked", "Already answered.")) });

    expect(await locker.lock("L1", "A1", "t1", 1)).toEqual({ ok: true });
  });

  test("an attempt that is over is reported as sealed", async () => {
    const locker = new AnswerLocker({ saveAnswer: async () => Promise.reject(new ApiError(409, "attempt_sealed", "Over.")) });

    expect(await locker.lock("L1", "A1", "t1", 1)).toMatchObject({ ok: false, sealed: true, message: "Over." });
  });

  test("a failure of the network is reported in words for the learner", async () => {
    const locker = new AnswerLocker({ saveAnswer: async () => Promise.reject(new Error("offline")) });

    expect(await locker.lock("L1", "A1", "t1", 1)).toEqual({ ok: false, sealed: false, message: "We couldn't save your answer. Try again." });
  });
});

describe("AttemptSubmitFlow", () => {
  const apis = (reads: TestSubmission[], submitted: { run_id: string | null } | Error) => {
    const calls: string[] = [];
    return {
      calls,
      api: {
        submitAttempt: async (_l: string, _a: string, answers?: Record<string, unknown>) => {
          calls.push(`submit ${JSON.stringify(answers)}`);
          if (submitted instanceof Error) throw submitted;
          return { submission_id: "A1", status: "graded" as const, ...submitted };
        },
        attempt: async () => {
          calls.push("read");
          return reads.shift()!;
        },
      },
    };
  };

  test("a lesson attempt comes back graded and no run is followed", async () => {
    const { follow, followed } = follower();
    const { api, calls } = apis([attempt()], { run_id: null });
    const seen: string[] = [];

    const result = await new AttemptSubmitFlow(api, follow).run("L1", "A1", { t10: 1 }, (a) => seen.push(a.status));

    expect(result.status).toBe("graded");
    expect([seen, followed.length, calls]).toEqual([["graded"], 0, ['submit {"t10":1}', "read"]]);
  });

  test("a legacy attempt is shown at once, followed to the end of its run and read again", async () => {
    const { follow, followed } = follower();
    const { api } = apis([attempt({ status: "grading", graded_at: null }), attempt()], { run_id: "R1" });
    const seen: string[] = [];

    const flow = new AttemptSubmitFlow(api, follow).run("L1", "A1", {}, (a) => seen.push(a.status));
    await tick();
    expect(seen).toEqual(["grading"]);
    followed[0].end();
    const result = await flow;

    expect(followed.map((f) => f.runId)).toEqual(["R1"]);
    expect([result.status, seen]).toEqual(["graded", ["grading", "graded"]]);
  });

  test("an attempt that is already over is read, not handed in again", async () => {
    const { follow } = follower();
    const { api, calls } = apis([attempt()], new ApiError(409, "attempt_sealed", "Over."));

    const result = await new AttemptSubmitFlow(api, follow).run("L1", "A1", {}, () => {});

    expect(result.status).toBe("graded");
    expect(calls).toEqual(["submit {}", "read"]);
  });

  test("another error rejects the flow", async () => {
    const { api } = apis([], new ApiError(400, "invalid_answers", "Bad answers."));

    await expect(new AttemptSubmitFlow(api, () => () => {}).run("L1", "A1", {}, () => {})).rejects.toThrow("Bad answers.");
  });

  test("leaving the page stops following the run and silences updates", async () => {
    const { follow, followed } = follower();
    const { api } = apis([attempt({ status: "grading" }), attempt()], { run_id: "R1" });
    const seen: string[] = [];
    const flow = new AttemptSubmitFlow(api, follow);

    const done = flow.run("L1", "A1", {}, (a) => seen.push(a.status));
    await tick();
    flow.dispose();
    followed[0].end();
    await done;

    expect(followed[0].stopped).toBe(true);
    expect(seen).toEqual(["grading"]);
  });
});
