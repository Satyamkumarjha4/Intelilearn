/**
 * Unit under test: `PipelineModel`, the state behind the progress screen while a lesson is being prepared.
 *
 * Why: this is all the learner sees for the minutes a lesson takes. A step that never turns "done", or a retry that
 * leaves no trace, makes a working pipeline look stuck.
 *
 * Use cases:
 * - shows the steps that belong to the lesson's stage
 * - a step is running while one of its nodes runs, and done once its last node is done
 * - a snapshot restores progress for a client that connected late
 * - a node retrying shows the attempt and reason on its step, and clears it when the node moves on
 * - model retries and fallbacks show on the step of the node that made the call
 * - events for steps that are not shown are ignored, and warnings are collected
 */
import { describe, expect, test } from "bun:test";

import { PipelineModel } from "./pipeline";
import type { RunEvent } from "./types";

const node = (name: string, status: "running" | "done" | "retrying", extra = {}): RunEvent => ({
  name: "node",
  data: { node: name, status, ...extra },
});

describe("PipelineModel", () => {
  test("shows the steps that belong to the stage", () => {
    expect(new PipelineModel("preparing_diagnostic").steps.map((s) => s.label)).toEqual(["Preparing your quiz"]);
    expect(new PipelineModel("generating_material").steps.map((s) => s.label)).toEqual(["Writing your study sheet"]);
    expect(new PipelineModel("generating_lesson").steps.map((s) => s.label)[0]).toBe("Assessing your level");
    expect(new PipelineModel("generating_lesson").steps).toHaveLength(7);
  });

  test("a step is running while a node runs and done once its last node is done", () => {
    const model = new PipelineModel("preparing_diagnostic");
    expect(model.steps[0].status).toBe("pending");

    model.apply(node("load_context", "running"));
    expect(model.steps[0].status).toBe("running");

    model.apply(node("load_context", "done"));
    expect(model.steps[0].status).toBe("running"); // started, not finished

    model.apply(node("publish_diagnostic", "done"));
    expect(model.steps[0].status).toBe("done");
  });

  test("a snapshot restores progress for a client that connected late", () => {
    const model = new PipelineModel("generating_lesson");

    model.apply({
      name: "snapshot",
      data: {
        status: "running",
        stage: "generating_lesson",
        lesson_id: "l",
        error: "",
        awaiting: null,
        node_status: { assess_learner: "done", plan_lesson: "running" },
      },
    });

    expect(model.steps.map((s) => s.status).slice(0, 3)).toEqual(["done", "running", "pending"]);
  });

  test("a retrying node shows the attempt and reason, cleared when the node moves on", () => {
    const model = new PipelineModel("preparing_diagnostic");

    model.apply(node("generate_diagnostic", "retrying", { attempt: 2, reason: "Needs 10 questions" }));
    expect(model.steps[0].note).toBe("Trying again (attempt 2): Needs 10 questions");

    model.apply(node("validate_diagnostic", "running"));
    expect(model.steps[0].note).toBe("");
  });

  test("model retries and fallbacks show on the step of the node that made the call", () => {
    const model = new PipelineModel("generating_lesson");

    model.apply({ name: "model", data: { node: "lesson.plan", model: "gemini", kind: "retry", reason: "Timeout" } });
    model.apply({ name: "model", data: { node: "page.generate", model: "llama", kind: "fallback", reason: "429" } });

    const notes = Object.fromEntries(model.steps.map((s) => [s.label, s.note]));
    expect(notes["Planning the lesson"]).toBe("Retrying gemini (Timeout)");
    expect(notes["Writing pages"]).toBe("Switched to llama (429)");
  });

  test("ignores events for steps that are not shown, and collects warnings", () => {
    const model = new PipelineModel("preparing_diagnostic");

    model.apply(node("plan_lesson", "running"));
    model.apply({ name: "model", data: { node: "page.generate", model: "m", kind: "retry", reason: "x" } });
    model.apply({ name: "warning", data: { message: "Dropped a widget" } });

    expect(model.steps[0]).toEqual({ label: "Preparing your quiz", status: "pending", note: "" });
    expect(model.warnings).toEqual(["Dropped a widget"]);
  });
});
