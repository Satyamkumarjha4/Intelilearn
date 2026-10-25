/**
 * Unit under test: `TestResultView` and `TestSubmitFlow`, how a submitted lesson test is followed and shown.
 *
 * Why: the score is what a learner takes from the test. A card that says "70%" while answers are still being graded
 * misleads them; a flow that never ends when the grading run fails leaves a spinner for ever; and one that keeps
 * reporting after the page was left updates something that is gone.
 *
 * Use cases:
 * - the summary says marks and percent, and "so far" while grading is incomplete
 * - each question is full, partial, none or pending, with a label that says so, and who marked it
 * - topics to revisit are listed
 * - a test marked at once is reported once and never follows a run
 * - a test with open-ended answers is reported at once, followed to the end of its run, then read again
 * - a failed grading is reported as failed with its reason
 * - an API error rejects the flow
 * - leaving the page stops following the run and silences updates
 */
import { describe, expect, test } from "bun:test";

import { TestResultView, TestSubmitFlow } from "./test-session";
import type { QuestionResult, ScoreCard, TestSubmission } from "./types";

const row = (over: Partial<QuestionResult> = {}): QuestionResult => ({
  id: "t1", type: "mcq", concept: "Halving", marks: 4, awarded: 4, correct: true, graded_by: "auto", feedback: "Correct.", solution: {}, ...over,
});
const card = (over: Partial<ScoreCard> = {}): ScoreCard => ({
  complete: true, score: { awarded: 14, available: 20, percent: 70 }, questions: [row()], topics_to_revisit: ["Halving", "Cost"], ...over,
});
const submission = (over: Partial<TestSubmission> = {}): TestSubmission => ({
  id: "S1", status: "graded", error: "", result: card(), submitted_at: "2026-01-01T00:00:00Z", graded_at: "2026-01-01T00:00:05Z", ...over,
});

describe("TestResultView", () => {
  test("summarises marks and percent, and says when it is not final", () => {
    expect(TestResultView.summary(card())).toBe("14 of 20 marks (70%)");
    expect(TestResultView.summary(card({ complete: false }))).toBe("14 of 20 marks (70%) so far");
  });

  test.each([
    [{ awarded: 4 }, "full", "Full marks"],
    [{ awarded: 2 }, "partial", "2 of 4 marks"],
    [{ awarded: 0 }, "none", "0 of 4 marks"],
    [{ awarded: null, correct: null, graded_by: "none" as const }, "pending", "Being graded"],
  ])("a question with %p is %s", (over, tone, label) => {
    const result = row(over);

    expect([TestResultView.tone(result), TestResultView.label(result)]).toEqual([tone, label]);
  });

  test("says who marked a question", () => {
    expect(TestResultView.source(row({ graded_by: "auto" }))).toBe("Marked automatically");
    expect(TestResultView.source(row({ graded_by: "model" }))).toBe("Graded by AI");
    expect(TestResultView.source(row({ graded_by: "none" }))).toBe("");
  });

  test("lists the topics to revisit", () => {
    expect(TestResultView.topics(card())).toBe("Halving, Cost");
    expect(TestResultView.topics(card({ topics_to_revisit: [] }))).toBe("");
  });
});

function fakes(reads: TestSubmission[], created = { submission_id: "S1", run_id: "R1" as string | null, status: "grading" as const }) {
  const calls: string[] = [];
  const api = {
    submitTest: async (_id: string, answers: Record<string, unknown>) => {
      calls.push(`submit ${JSON.stringify(answers)}`);
      return created;
    },
    submission: async () => {
      calls.push("read");
      return reads.shift()!;
    },
  };
  const followed: { runId: string; end: () => void; stopped: boolean }[] = [];
  const follow = (runId: string, end: () => void) => {
    const entry = { runId, end, stopped: false };
    followed.push(entry);
    return () => {
      entry.stopped = true;
    };
  };
  return { api, follow, followed, calls };
}

describe("TestSubmitFlow", () => {
  test("a test marked at once is reported once and no run is followed", async () => {
    const { api, follow, followed } = fakes([submission()], { submission_id: "S1", run_id: null, status: "graded" as never });
    const seen: string[] = [];

    const result = await new TestSubmitFlow(api, follow).run("L1", { t1: 1 }, (s) => seen.push(s.status));

    expect(result.status).toBe("graded");
    expect([seen, followed.length]).toEqual([["graded"], 0]);
  });

  test("open-ended answers are shown at once, followed to the end of the run, then read again", async () => {
    const pending = submission({ status: "grading", graded_at: null, result: card({ complete: false }) });
    const { api, follow, followed, calls } = fakes([pending, submission()]);
    const seen: string[] = [];

    const flow = new TestSubmitFlow(api, follow).run("L1", { t1: 1 }, (s) => seen.push(`${s.status}:${s.result?.complete}`));
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
    expect(seen).toEqual(["grading:false"]);
    followed[0].end();
    const result = await flow;

    expect(followed.map((f) => f.runId)).toEqual(["R1"]);
    expect(seen).toEqual(["grading:false", "graded:true"]);
    expect([result.status, calls.filter((c) => c === "read").length]).toEqual(["graded", 2]);
  });

  test("a failed grading is reported as failed with its reason", async () => {
    const pending = submission({ status: "grading", graded_at: null });
    const failed = submission({ status: "failed", error: "Every AI model failed.", result: card({ complete: false }) });
    const { api, follow, followed } = fakes([pending, failed]);

    const flow = new TestSubmitFlow(api, follow).run("L1", {}, () => {});
    await new Promise((r) => setTimeout(r, 0));
    followed[0].end();

    expect(await flow).toMatchObject({ status: "failed", error: "Every AI model failed." });
  });

  test("an API error rejects the flow", async () => {
    const api = { submitTest: async () => Promise.reject(new Error("409")), submission: async () => submission() };

    await expect(new TestSubmitFlow(api, () => () => {}).run("L1", {}, () => {})).rejects.toThrow("409");
  });

  test("leaving the page stops following the run and silences updates", async () => {
    const pending = submission({ status: "grading", graded_at: null });
    const { api, follow, followed } = fakes([pending, submission()]);
    const seen: string[] = [];
    const flow = new TestSubmitFlow(api, follow);

    const done = flow.run("L1", {}, (s) => seen.push(s.status));
    await new Promise((r) => setTimeout(r, 0));
    flow.dispose();
    followed[0].end();
    await done;

    expect(followed[0].stopped).toBe(true);
    expect(seen).toEqual(["grading"]);
  });
});
