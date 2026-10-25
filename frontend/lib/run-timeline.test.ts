/**
 * Unit under test: `RunTimeline`, which lays a run's steps out for the console's timeline (phase headings, one lane
 * per step, a bar placed by start offset and sized by duration).
 *
 * Why: the timeline is how staff see where a run spent its time and where it broke. A bar placed or sized wrongly
 * (past the lane's edge, invisible because it was quick, or drawn for a step whose time was never kept) points at
 * the wrong step, and the detail panel is the only place this is shown.
 *
 * Use cases:
 * - turns start offsets and durations into percentages of the run's length
 * - keeps a very short step visible (a minimum width) and inside the lane (never past the right edge)
 * - sizes the lanes by the run's own time when that is longer than the last step (a run waiting for the learner)
 * - draws a step that is still waiting from its start to the end of the run, with no duration written
 * - draws no bar for a step whose time was not kept, and writes "—" for its duration
 * - groups steps under their phase in the order diagnose, author, build, after, other, keeping start order inside it
 * - leaves out a phase that has no steps, and handles a run with no steps at all
 * - writes the hover text of a bar (node, state, start, duration, whether it ran more than once) and where the
 *   hover text sits so it stays on screen
 */
import { describe, expect, test } from "bun:test";

import { RunTimeline } from "./run-timeline";
import type { TimelineStep } from "./types";

const step = (patch: Partial<TimelineStep> & { node: string }): TimelineStep => ({
  phase: "build",
  start_offset_s: 0,
  duration_s: 10,
  state: "ran",
  ...patch,
});

const lanes = (steps: TimelineStep[], runDuration: number | null = null) =>
  RunTimeline.layout(steps, runDuration).phases.flatMap((phase) => phase.lanes);

describe("bar position", () => {
  test("turns offsets and durations into percentages of the run's length", () => {
    const [a, b] = lanes([step({ node: "a", start_offset_s: 0, duration_s: 50 }), step({ node: "b", start_offset_s: 50, duration_s: 50 })]);

    expect([a.bar, b.bar]).toEqual([
      { left: 0, width: 50 },
      { left: 50, width: 50 },
    ]);
  });

  test("keeps a very short step visible, and inside the lane at the right edge", () => {
    const [long, blink, last] = lanes([
      step({ node: "long", start_offset_s: 0, duration_s: 1000 }),
      step({ node: "blink", start_offset_s: 500, duration_s: 0.2 }),
      step({ node: "last", start_offset_s: 1000, duration_s: 0 }),
    ]);

    expect(long.bar).toEqual({ left: 0, width: 100 });
    expect(blink.bar).toEqual({ left: 50, width: RunTimeline.MIN_WIDTH });
    expect(last.bar!.width).toBe(RunTimeline.MIN_WIDTH);
    expect(last.bar!.left + last.bar!.width).toBeCloseTo(100, 6);
  });

  test("uses the run's own time when that is longer than its last step", () => {
    const [only] = lanes([step({ node: "only", start_offset_s: 0, duration_s: 30 })], 120);

    expect(only.bar).toEqual({ left: 0, width: 25 });
  });

  test("ignores a run time that is shorter than its steps, or missing", () => {
    const [short] = lanes([step({ node: "a", duration_s: 40 })], 5);
    const [none] = lanes([step({ node: "a", duration_s: 40 })], null);

    expect(short.bar!.width).toBe(100);
    expect(none.bar!.width).toBe(100);
  });

  test("draws a waiting step from its start to the end of the run, and writes no duration", () => {
    const [wait] = lanes([step({ node: "await_diagnostic", start_offset_s: 18, duration_s: null, state: "waiting" })], 60);

    expect(wait.bar).toEqual({ left: 30, width: 70 });
    expect(wait.durationText).toBe("—");
  });

  test("draws no bar for a step whose time was not kept", () => {
    const [old] = lanes([step({ node: "old", start_offset_s: null, duration_s: null })], 30);

    expect(old.bar).toBeNull();
    expect(old.durationText).toBe("—");
  });

  test("copes with a run whose steps all have zero length", () => {
    const [zero] = lanes([step({ node: "z", start_offset_s: 0, duration_s: 0 })]);

    expect(zero.bar).toEqual({ left: 0, width: RunTimeline.MIN_WIDTH });
  });

  test("keeps the state and the written duration of each lane", () => {
    const [ok, retried, failed] = lanes([
      step({ node: "ok", duration_s: 2.4 }),
      step({ node: "again", state: "retried", duration_s: 41 }),
      step({ node: "boom", state: "failed", duration_s: 252 }),
    ]);

    expect([ok.state, retried.state, failed.state]).toEqual(["ran", "retried", "failed"]);
    expect([ok.durationText, retried.durationText, failed.durationText]).toEqual(["2.4 s", "41 s", "4 m 12 s"]);
  });
});

describe("phases", () => {
  test("groups steps by phase in the order diagnose, author, build, after, other", () => {
    const view = RunTimeline.layout(
      [
        step({ node: "g", phase: "other", start_offset_s: 1 }),
        step({ node: "f", phase: "post", start_offset_s: 2 }),
        step({ node: "e", phase: "build", start_offset_s: 3 }),
        step({ node: "d", phase: "author", start_offset_s: 4 }),
        step({ node: "c", phase: "diagnose", start_offset_s: 5 }),
      ],
      null,
    );

    expect(view.phases.map((p) => [p.phase, p.label])).toEqual([
      ["diagnose", "Diagnose"],
      ["author", "Author"],
      ["build", "Build"],
      ["post", "After"],
      ["other", "Other"],
    ]);
  });

  test("keeps the steps in the order they came inside a phase, and a repeated node name apart", () => {
    const view = RunTimeline.layout(
      [step({ node: "render_check", start_offset_s: 1 }), step({ node: "code.repair", start_offset_s: 5 }), step({ node: "render_check", start_offset_s: 9 })],
      null,
    );

    const build = view.phases[0];
    expect(build.lanes.map((l) => l.node)).toEqual(["render_check", "code.repair", "render_check"]);
    expect(new Set(build.lanes.map((l) => l.key)).size).toBe(3);
  });

  test("leaves out a phase with no steps, and has none for a run with no steps", () => {
    const view = RunTimeline.layout([step({ node: "a", phase: "author" })], null);

    expect(view.phases.map((p) => p.phase)).toEqual(["author"]);
    expect(RunTimeline.layout([], 12).phases).toEqual([]);
  });

  test("puts a phase it does not know with the others instead of dropping the step", () => {
    const view = RunTimeline.layout([step({ node: "new", phase: "surprise" as TimelineStep["phase"] })], null);

    expect(view.phases.map((p) => [p.phase, p.lanes.length])).toEqual([["other", 1]]);
  });
});

describe("hover text", () => {
  test("writes the node, state, start, duration and whether it ran more than once", () => {
    const [lane] = lanes([step({ node: "interactive.generate", start_offset_s: 128, duration_s: 61, state: "retried" })]);

    expect(lane.tip).toEqual({
      title: "interactive.generate",
      rows: [
        ["Result", "Ran again after a failed check"],
        ["Started", "2 m 08 s into the run"],
        ["Took", "1 m 01 s"],
      ],
    });
  });

  test("says what a waiting, a failed and a step without times look like", () => {
    const [wait, fail, old] = lanes([
      step({ node: "w", state: "waiting", duration_s: null, start_offset_s: 18 }),
      step({ node: "f", state: "failed", start_offset_s: 0, duration_s: 3 }),
      step({ node: "o", start_offset_s: null, duration_s: null }),
    ]);

    expect(wait.tip.rows).toEqual([
      ["Result", "Waiting for the learner"],
      ["Started", "18 s into the run"],
      ["Took", "—"],
    ]);
    expect(fail.tip.rows[0]).toEqual(["Result", "Failed"]);
    expect(old.tip.rows).toEqual([
      ["Result", "Ran"],
      ["Started", "—"],
      ["Took", "—"],
    ]);
  });

  test("describes the lane as one sentence for assistive technology", () => {
    const [lane] = lanes([step({ node: "page.compile", state: "failed", start_offset_s: 201, duration_s: 38 })]);

    expect(lane.label).toBe("page.compile: Failed. Started 3 m 21 s into the run. Took 38 s.");
  });

  test("keeps the hover text on screen by aligning it to the near edge of a bar at either end", () => {
    const [left, mid, right] = lanes([
      step({ node: "l", start_offset_s: 0, duration_s: 10 }),
      step({ node: "m", start_offset_s: 450, duration_s: 100 }),
      step({ node: "r", start_offset_s: 900, duration_s: 100 }),
    ]);

    expect([left.tipAlign, mid.tipAlign, right.tipAlign]).toEqual(["start", "center", "end"]);
  });
});
