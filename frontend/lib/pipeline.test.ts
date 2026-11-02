/**
 * Unit under test: `PipelineModel`, the state behind the building screen while a lesson is being prepared.
 *
 * Why: this is all the learner sees for the minutes a lesson takes. A step that never turns "done", a percentage that
 * runs backwards, a retry that leaves no trace, or a technical note that leaks (a model name, a stack message) makes a
 * working build look stuck or frightening.
 *
 * Use cases:
 * - shows the friendly steps that belong to the lesson's stage; while the lesson is built the quiz step is already done
 * - a step is running while one of its nodes runs, and done once its last node is done; the label follows (doing/done)
 * - a snapshot restores progress for a client that connected late
 * - the percentage is the steps done out of all of them, and nothing is measurable until a step of this run is done (the
 *   quiz a lesson build begins after does not count: the bar just moves, with no "13%")
 * - the run's start time is read from the snapshot ("Started 2 min ago"), and is unknown until it arrives
 * - while the basics check is being prepared its steps say so
 * - a retry starts while the lesson still reads "failed": one calm step, not a single "Preparing your quiz" for the whole
 *   rebuild, and once the lesson's real stage is known the model switches to its steps and keeps what it has seen
 * - a lesson the learner rated themselves into has no quick check to prepare: its first step is setting the starting
 *   point, nothing is assumed done before it, and only a Beginner, who was not tested, has a step that chooses what to
 *   learn first; the path is read from the lesson (the entry, and the stars as the API sends them)
 * - sheets written together (the choice after a perfect quick check, a lesson that asked for sheets, another sheet or
 *   two on a ready lesson) have their own steps (writing, then checking and putting them together): a lesson writing
 *   sheets shows them from the start, counts the sheets written, finishes writing when the join starts (whatever the
 *   number of sheets), and a snapshot from a client that connected late does the same
 * - a lesson that asked for sheets starts with finding the level (the quiz's assessment, or the rating's starting
 *   point) and then has the sheets' steps; it never has the lesson's steps, prerequisites included
 * - the headline is the step being worked on
 * - the time a step took is measured from when the client saw it start to when it finished, and keeps counting while
 *   it runs; a step first seen finished started when the one before it ended; steps restored from a snapshot have no time
 * - a sub-line says how far a step has got where the events allow ("2 of 3 pages written")
 * - a node retrying or a model retry or fallback sets one calm "recovered" flag and never names a model
 * - events for steps that are not shown are ignored, and warnings are collected and rewritten in plain words
 * - elapsed times read as seconds, then minutes
 */
import { describe, expect, test } from "bun:test";

import { Elapsed, PipelineModel, PipelinePaths } from "./pipeline";
import type { RunEvent } from "./types";

const node = (name: string, status: "running" | "done" | "retrying", extra = {}): RunEvent => ({
  name: "node",
  data: { node: name, status, ...extra },
});
const labels = (model: PipelineModel) => model.steps.map((s) => s.label);

/** A model whose clock is moved by hand, in seconds. */
function clocked(stage: ConstructorParameters<typeof PipelineModel>[0]) {
  let now = 0;
  const model = new PipelineModel(stage, () => now * 1000);
  return { model, at: (seconds: number) => void (now = seconds) };
}

describe("steps", () => {
  test("shows the friendly steps that belong to the stage", () => {
    expect(labels(new PipelineModel("preparing_diagnostic"))).toEqual([
      "Getting to know you", "Writing your questions", "Checking the questions", "Getting your quick check ready",
    ]);
    expect(labels(new PipelineModel("preparing_diagnostic", Date.now, "prerequisite"))).toEqual([
      "Getting to know you", "Writing your basics questions", "Checking the questions", "Getting your basics check ready",
    ]);
    expect(labels(new PipelineModel("generating_material"))).toEqual([
      "Writing your study sheets", "Checking and putting them together",
    ]);
    expect(labels(new PipelineModel("ready"))).toEqual(["Writing your study sheets", "Checking and putting them together"]);
    expect(labels(new PipelineModel("generating_lesson"))).toEqual([
      "Prepared your quiz",
      "Working out your starting point",
      "Planning the lesson",
      "Writing pages",
      "Finding images & building interactives",
      "Checking it fits your level",
      "Building the lesson",
      "Test-driving it in a safe browser",
    ]);
  });

  test("while the lesson is built the quiz step is already done", () => {
    const model = new PipelineModel("generating_lesson");

    expect(model.steps.map((s) => s.status)).toEqual(["done", "pending", "pending", "pending", "pending", "pending", "pending", "pending"]);
  });

  test("a step is running while a node runs and done once its last node is done, and its label follows", () => {
    const model = new PipelineModel("preparing_diagnostic");
    expect(model.steps[0].status).toBe("pending");

    model.apply(node("load_context", "running"));
    expect(model.steps[0]).toMatchObject({ status: "running", label: "Getting to know you" });

    model.apply(node("generate_diagnostic", "done"));
    expect(model.steps.map((s) => s.status)).toEqual(["running", "done", "pending", "pending"]); // started, not finished

    model.apply(node("load_context", "done"));
    expect(model.steps[0]).toMatchObject({ status: "done", label: "Got to know you" });
  });

  test("a snapshot restores progress for a client that connected late", () => {
    const model = new PipelineModel("generating_lesson");

    model.apply({
      name: "snapshot",
      data: {
        status: "running", stage: "generating_lesson", lesson_id: "l", error: "", awaiting: null,
        node_status: { assess_learner: "done", plan_lesson: "running" },
      },
    });

    expect(model.steps.map((s) => s.status).slice(0, 4)).toEqual(["done", "done", "running", "pending"]);
  });

  test("events for steps that are not shown are ignored", () => {
    const model = new PipelineModel("preparing_diagnostic");

    model.apply(node("plan_lesson", "running"));
    model.apply({ name: "model", data: { node: "page.generate", model: "m", kind: "retry", reason: "x" } });

    expect(model.steps[0]).toMatchObject({ status: "pending", detail: "", elapsedMs: null });
    expect(model.recovered).toBe(false);
  });
});

describe("progress", () => {
  test("the percentage is the steps done out of all of them", () => {
    const model = new PipelineModel("generating_lesson");
    expect(model.percent).toBe(13); // 1 of 8

    model.apply(node("assess_learner", "done"));
    model.apply(node("validate_plan", "done"));

    expect(model.percent).toBe(38); // 3 of 8
    expect(new PipelineModel("preparing_diagnostic").percent).toBe(0);
  });

  test("the headline is the step being worked on, else the first one waiting, else a closing line", () => {
    const model = new PipelineModel("generating_lesson");
    expect(model.headline).toBe("Working out your starting point");

    model.apply(node("plan_lesson", "running"));
    expect(model.headline).toBe("Planning the lesson");

    for (const done of ["plan_lesson", "assess_learner", "validate_plan", "authored_join", "widgets_join", "alignment_judge", "assemble_document", "persist_lesson"]) {
      model.apply(node(done, "done"));
    }
    expect(model.headline).toBe("All done");
    expect(model.percent).toBe(100);
  });
});

describe("measurable", () => {
  test("nothing can be measured until the first step is done", () => {
    const model = new PipelineModel("preparing_diagnostic");
    expect(model.measurable).toBe(false);

    model.apply(node("load_context", "running"));
    expect(model.measurable).toBe(false);

    model.apply(node("load_context", "done"));
    expect([model.measurable, model.percent]).toEqual([true, 25]);
  });

  test("a build that begins after the quiz is not measurable until one of its own steps is done", () => {
    const model = new PipelineModel("generating_lesson");
    expect(model.measurable).toBe(false);

    model.apply(node("assess_learner", "running"));
    expect(model.measurable).toBe(false);

    model.apply(node("assess_learner", "done"));
    expect(model.measurable).toBe(true);
    expect(model.percent).toBeGreaterThan(Math.round(100 / 8)); // the finished quiz still counts towards the total
  });

  test("a snapshot that restores finished steps makes the build measurable", () => {
    const model = new PipelineModel("generating_lesson");

    model.apply({
      name: "snapshot",
      data: { status: "running", stage: "generating_lesson", lesson_id: "l", error: "", awaiting: null, node_status: { assess_learner: "done" } },
    });

    expect(model.measurable).toBe(true);
  });
});

describe("started", () => {
  const snapshot = (started_at?: string): RunEvent => ({
    name: "snapshot",
    data: { status: "running", stage: "generating_lesson", lesson_id: "l", error: "", awaiting: null, node_status: {}, ...(started_at ? { started_at } : {}) },
  });

  test("is unknown until the snapshot says, then is the run's start", () => {
    const model = new PipelineModel("generating_lesson");
    expect(model.startedAt).toBeNull();

    model.apply(snapshot("2026-10-25T12:00:00Z"));
    expect(model.startedAt).toBe(Date.parse("2026-10-25T12:00:00Z"));
  });

  test.each([[undefined], ["soon"]])("a snapshot with %p leaves it unknown", (value) => {
    const model = new PipelineModel("generating_lesson");
    model.apply(snapshot(value));

    expect(model.startedAt).toBeNull();
  });
});

describe("time", () => {
  test("a step is timed from when it was seen to start to its own end, and counts while it runs", () => {
    const { model, at } = clocked("preparing_diagnostic");
    at(0);
    model.apply(node("load_context", "running"));
    at(12);
    expect(model.steps[0].elapsedMs).toBe(12_000);

    at(30);
    model.apply(node("load_context", "done"));
    at(99);
    expect(model.steps[0].elapsedMs).toBe(30_000);
  });

  test("a step first seen finished started when the one before it ended", () => {
    const { model, at } = clocked("generating_lesson");
    at(5);
    model.apply(node("assess_learner", "done"));
    at(20);
    model.apply(node("plan_lesson", "running"));
    at(26);

    expect(model.steps.map((s) => s.elapsedMs)).toEqual([null, 5000, 6000, null, null, null, null, null]);
  });

  test("a step restored from a snapshot has no time, a running one counts from now", () => {
    const { model, at } = clocked("generating_lesson");
    at(100);
    model.apply({
      name: "snapshot",
      data: {
        status: "running", stage: "generating_lesson", lesson_id: "l", error: "", awaiting: null,
        node_status: { assess_learner: "done", plan_lesson: "running" },
      },
    });
    at(104);

    expect(model.steps.map((s) => s.elapsedMs).slice(0, 4)).toEqual([null, null, 4000, null]);
  });
});

describe("sub-lines", () => {
  test("say how far a step has got where the events allow", () => {
    const model = new PipelineModel("generating_lesson");
    model.apply(node("write_page", "running"));
    expect(model.steps[3].detail).toBe("");

    model.apply(node("write_page", "done"));
    model.apply(node("write_page", "done"));
    expect(model.steps[3].detail).toBe("2 of 3 pages written");

    model.apply(node("build_interactive", "done"));
    expect(model.steps[4].detail).toBe("1 interactive built");
    model.apply(node("build_interactive", "done"));
    expect(model.steps[4].detail).toBe("2 interactives built");

    model.apply(node("compile_page", "done"));
    expect(model.steps[6].detail).toBe("1 of 3 pages built");
  });

  test("a finished step needs no sub-line", () => {
    const model = new PipelineModel("generating_lesson");
    for (const done of ["write_page", "write_page", "write_page", "write_test", "authored_join"]) model.apply(node(done, "done"));

    expect(model.steps[3]).toMatchObject({ status: "done", detail: "" });
  });
});

describe("recovery and notes", () => {
  test("a node retrying sets the calm flag, and nothing technical is kept", () => {
    const model = new PipelineModel("preparing_diagnostic");

    model.apply(node("generate_diagnostic", "retrying", { attempt: 2, reason: "Needs 10 questions" }));

    expect(model.recovered).toBe(true);
    expect(JSON.stringify(model.steps)).not.toContain("Needs 10 questions");
  });

  test("a model retry or fallback sets the flag without naming the model", () => {
    const retry = new PipelineModel("generating_lesson");
    retry.apply({ name: "model", data: { node: "lesson.plan", model: "gemini-secret", kind: "retry", reason: "Timeout" } });
    const fallback = new PipelineModel("generating_lesson");
    fallback.apply({ name: "model", data: { node: "page.generate", model: "llama-secret", kind: "fallback", reason: "429" } });

    for (const model of [retry, fallback]) {
      expect(model.recovered).toBe(true);
      expect(JSON.stringify([model.steps, model.notes])).not.toMatch(/secret|Timeout|429/);
    }
  });

  test("warnings are collected and rewritten in plain words", () => {
    const model = new PipelineModel("generating_lesson");

    model.apply({ name: "warning", data: { message: "The core page uses the standard layout: generated code kept failing (x)" } });
    model.apply({ name: "warning", data: { message: "The advanced page uses the standard layout after a failed repair" } });

    expect(model.warnings).toHaveLength(2);
    expect(model.notes).toEqual(["We used a simpler layout for one of the pages."]);
  });
});

describe("Elapsed.format", () => {
  test.each([
    [0, "0s"], [400, "0s"], [1000, "1s"], [59_900, "59s"], [60_000, "1m 00s"], [125_000, "2m 05s"],
  ])("%i ms reads %s", (ms, text) => {
    expect(Elapsed.format(ms)).toBe(text);
  });
});

describe("a retry that starts while the lesson still reads failed", () => {
  test("shows one step that says we are picking up where it stopped, and is not measurable", () => {
    const model = new PipelineModel("failed");

    expect(model.steps.map((step) => step.label)).toEqual(["Picking up where it stopped"]);
    expect(model.headline).toBe("Picking up where it stopped");
    expect(model.measurable).toBe(false);
  });

  test("switches to the steps of the real stage and keeps the events it already saw", () => {
    const model = new PipelineModel("failed");
    model.apply(node("assess_learner", "done"));
    model.apply(node("plan_lesson", "running"));

    model.setStage("generating_lesson");

    const steps = Object.fromEntries(model.steps.map((step) => [step.key, step.status]));
    expect(steps.quiz).toBe("done");
    expect(steps.assess).toBe("done");
    expect(steps.plan).toBe("running");
    expect(model.headline).toBe("Planning the lesson");
    expect(model.measurable).toBe(true);
  });

  test("does not restart when the stage is set to the one it already has", () => {
    const model = new PipelineModel("preparing_diagnostic");
    model.apply(node("load_context", "done"));

    model.setStage("preparing_diagnostic");

    expect(model.percent).toBe(25);
  });
});

describe("a lesson with no quick check", () => {
  const rated = { rated: true, beginner: false };
  const rawBeginner = { rated: true, beginner: true };

  test("its first step sets the starting point, and while it starts there is nothing else to show", () => {
    expect(labels(new PipelineModel("preparing_diagnostic", Date.now, "", rated))).toEqual(["Setting your starting point"]);
  });

  test("a rated lesson that is being built has no quiz step, and nothing is assumed done", () => {
    const model = new PipelineModel("generating_lesson", Date.now, "", rated);

    expect(labels(model)).toEqual([
      "Setting your starting point", "Planning the lesson", "Writing pages", "Finding images & building interactives",
      "Checking it fits your level", "Building the lesson", "Test-driving it in a safe browser",
    ]);
    expect(model.steps.every((s) => s.status === "pending")).toBe(true);
    expect(model.measurable).toBe(false);
  });

  test("a Beginner also has what to learn first chosen, after the starting point", () => {
    const labelsOf = labels(new PipelineModel("generating_lesson", Date.now, "", rawBeginner));

    expect(labelsOf.slice(0, 3)).toEqual(["Setting your starting point", "Choosing what to learn first", "Planning the lesson"]);
  });

  test("the steps follow the events of the run", () => {
    const model = new PipelineModel("generating_lesson", Date.now, "", rawBeginner);

    for (const name of ["load_context", "entry_router", "assess_from_source", "level_gate"]) {
      model.apply(node(name, "running"));
      model.apply(node(name, "done"));
    }
    model.apply(node("plan_prerequisites", "running"));

    expect(model.steps.slice(0, 3).map((s) => [s.key, s.status])).toEqual([
      ["rated_start", "done"], ["prerequisites", "running"], ["plan", "pending"],
    ]);
    expect(model.headline).toBe("Choosing what to learn first");
    expect(model.measurable).toBe(true);
  });

  test("a model that learns the stage later keeps what it saw", () => {
    const model = new PipelineModel("preparing_diagnostic", Date.now, "", rawBeginner);
    model.apply(node("assess_from_source", "done"));

    model.setStage("generating_lesson");

    expect(model.steps[0]).toMatchObject({ key: "rated_start", status: "done" });
  });

  test("a quick check lesson is unchanged", () => {
    expect(labels(new PipelineModel("generating_lesson", Date.now, "", PipelinePaths.QUICK_CHECK))[0]).toBe("Prepared your quiz");
  });

  test("a retry still shows its one calm step", () => {
    expect(labels(new PipelineModel("failed", Date.now, "", rated))).toEqual(["Picking up where it stopped"]);
  });
});

describe("the path of a lesson", () => {
  test.each([
    [{ entry: "diagnostic", self_rating: null, intent: "lesson" }, { rated: false, beginner: false, sheets: false }],
    [{ entry: "self_rating", self_rating: 0.5, intent: "lesson" }, { rated: true, beginner: true, sheets: false }],
    [{ entry: "self_rating", self_rating: 1.5, intent: "lesson" }, { rated: true, beginner: true, sheets: false }],
    [{ entry: "self_rating", self_rating: 2, intent: "lesson" }, { rated: true, beginner: false, sheets: false }],
    [{ entry: "self_rating", self_rating: 5, intent: "lesson" }, { rated: true, beginner: false, sheets: false }],
    [{ entry: "self_rating", self_rating: null, intent: "lesson" }, { rated: true, beginner: false, sheets: false }],
    [{ entry: "diagnostic", self_rating: null, intent: "sheets" }, { rated: false, beginner: false, sheets: true }],
    [{ entry: "self_rating", self_rating: 0.5, intent: "sheets" }, { rated: true, beginner: false, sheets: true }], // nothing to prepare for
  ] as const)("%j", (lesson, path) => {
    expect(PipelinePaths.of(lesson)).toEqual(path);
  });
});

describe("study sheets written together", () => {
  test("a lesson writing sheets shows the group's steps from the start, with no event needed", () => {
    const model = new PipelineModel("generating_material");

    expect(labels(model)).toEqual(["Writing your study sheets", "Checking and putting them together"]);
    model.apply(node("plan_sheets", "running"));

    expect(labels(model)).toEqual(["Writing your study sheets", "Checking and putting them together"]);
    expect(model.headline).toBe("Writing your study sheets");
  });

  test("the sheets are counted, and writing is done when the join starts, whatever the number", () => {
    const model = new PipelineModel("generating_material");
    model.apply(node("plan_sheets", "running"));
    model.apply(node("plan_sheets", "done"));
    model.apply(node("generate_sheet", "running"));
    model.apply(node("generate_sheet", "done"));

    expect(model.steps[0]).toMatchObject({ status: "running", detail: "1 sheet written" });

    model.apply(node("generate_sheet", "done"));
    expect(model.steps[0]).toMatchObject({ status: "running", detail: "2 sheets written" });

    model.apply(node("sheets_join", "running"));
    expect(model.steps.map((s) => s.status)).toEqual(["done", "running"]);
    model.apply(node("sheets_join", "done"));
    expect(model.steps.map((s) => s.status)).toEqual(["done", "done"]);
    expect(model.percent).toBe(100);
  });

  test("one sheet alone finishes writing when the join starts", () => {
    const model = new PipelineModel("ready");
    for (const name of ["load_context", "plan_sheets", "generate_sheet"]) {
      model.apply(node(name, "running"));
      model.apply(node(name, "done"));
    }
    model.apply(node("sheets_join", "running"));

    expect(model.steps.map((s) => s.status)).toEqual(["done", "running"]);
  });

  test("a sheet written again shows writing as running while it is", () => {
    const model = new PipelineModel("generating_material");
    for (const status of ["running", "done"] as const) model.apply(node("generate_sheet", status));
    model.apply(node("generate_sheet", "done"));
    model.apply(node("sheets_join", "running"));
    model.apply(node("generate_sheet", "running"));

    expect(model.steps[0].status).toBe("running");
  });

  test("a snapshot from a client that connected late shows the group too", () => {
    const model = new PipelineModel("generating_material");

    model.apply({
      name: "snapshot",
      data: {
        status: "running", stage: "generating_material", lesson_id: "l", error: "", awaiting: null,
        node_status: { plan_sheets: "done", generate_sheet: "running" },
      },
    });

    expect(labels(model)).toEqual(["Writing your study sheets", "Checking and putting them together"]);
    expect(model.steps[0].status).toBe("running");
  });

  test("a lesson that is being built never switches to the sheets' steps", () => {
    const model = new PipelineModel("generating_lesson");

    model.apply(node("generate_sheet", "running"));

    expect(labels(model)[0]).toBe("Prepared your quiz");
  });
});

describe("a lesson that asked for sheets", () => {
  const quickCheck = { rated: false, beginner: false, sheets: true };
  const rated = { rated: true, beginner: false, sheets: true };

  test("the quiz is prepared as for any lesson", () => {
    expect(labels(new PipelineModel("preparing_diagnostic", Date.now, "", quickCheck))).toEqual(
      labels(new PipelineModel("preparing_diagnostic")),
    );
  });

  test("after the quiz it works out the starting point, then writes the sheets", () => {
    expect(labels(new PipelineModel("generating_material", Date.now, "", quickCheck))).toEqual([
      "Working out your starting point", "Writing your study sheets", "Checking and putting them together",
    ]);
  });

  test("a rated one sets the starting point from the rating, then writes the sheets", () => {
    expect(labels(new PipelineModel("preparing_diagnostic", Date.now, "", rated))).toEqual(["Setting your starting point"]);
    expect(labels(new PipelineModel("generating_material", Date.now, "", rated))).toEqual([
      "Setting your starting point", "Writing your study sheets", "Checking and putting them together",
    ]);
  });

  test("seeing the sheets' nodes does not drop the starting point from the steps", () => {
    const model = new PipelineModel("generating_material", Date.now, "", quickCheck);
    model.apply(node("assess_learner", "done"));

    model.apply(node("plan_sheets", "running"));

    expect(model.steps.map((s) => [s.key, s.status])).toEqual([["assess", "done"], ["sheets_write", "running"], ["sheets_save", "pending"]]);
  });

  test("it never has the steps of a lesson, whatever stage it reports", () => {
    for (const stage of ["generating_material", "ready"] as const) {
      const all = labels(new PipelineModel(stage, Date.now, "", rated)).join("|");
      expect(all).not.toMatch(/Planning the lesson|Writing pages|Choosing what to learn first/);
    }
  });
});
