/**
 * Unit under test: `QuizProgress`, the steps shown while a quiz is being made.
 *
 * Why: making a quiz takes a little while, and a learner who sees nothing happen reloads or leaves. The graph's own step
 * names mean nothing to them, so the steps are four plain sentences, worked out from which graph steps have run, with the
 * one in progress marked. A retake already knows the level, so it should not say it is finding it.
 *
 * Use cases:
 * - before anything has run, all four steps are there and the first is active
 * - each step is done once a later one has begun, and the one that has begun last is active
 * - the final step is done when it has finished
 * - a retake, which goes straight from loading to planning, has three steps
 * - the calibration walk's steps (the pool being written, the walk itself) belong to finding the level
 */
import { describe, expect, test } from "bun:test";

import { QuizProgress } from "./quiz-progress";
import type { NodeStatus } from "./types";

const states = (status: Record<string, NodeStatus>) => QuizProgress.steps(status).map((s) => `${s.label}: ${s.state}`);

describe("the steps", () => {
  test("before anything has run all four are there and the first is active", () => {
    expect(states({})).toEqual([
      "Finding your level: active",
      "Planning your questions: waiting",
      "Writing your questions: waiting",
      "Getting everything ready: waiting",
    ]);
  });

  test("a step is done when a later one has begun, and the latest is active", () => {
    expect(states({ load_quiz: "done", level_from_rating: "done", plan_quiz: "done", plan_batches: "running" })).toEqual([
      "Finding your level: done",
      "Planning your questions: active",
      "Writing your questions: waiting",
      "Getting everything ready: waiting",
    ]);
    expect(states({ level_from_rating: "done", plan_batches: "done", generate_questions: "running" })[2]).toBe("Writing your questions: active");
  });

  test("the last step is done when it has finished", () => {
    const done = { level_from_rating: "done", plan_batches: "done", generate_questions: "done", questions_join: "done", persist_attempt: "done" } as const;

    expect(states(done).every((line) => line.endsWith("done"))).toBe(true);
    expect(states({ ...done, persist_attempt: "running" })[3]).toBe("Getting everything ready: active");
  });

  test("a retake has no step for the level", () => {
    expect(states({ load_quiz: "done", resolve_source: "done", plan_quiz: "running" })).toEqual([
      "Planning your questions: active",
      "Writing your questions: waiting",
      "Getting everything ready: waiting",
    ]);
  });

  test("the warm-up's own steps are part of finding the level", () => {
    expect(states({ load_quiz: "done", generate_pool: "running" })[0]).toBe("Finding your level: active");
    expect(states({ generate_pool: "done", validate_pool: "done", publish_calibration: "done", await_calibration: "running" })[1]).toBe("Planning your questions: waiting");
  });
});
