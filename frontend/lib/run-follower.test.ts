/**
 * Unit under test: `RunFollower`, which keeps the console's open run current while it is running.
 *
 * Why: the timeline is read while a run is still going. The events stream is open only to the learner whose run it
 * is, so for anyone else's run it fails; the follower must then still keep the timeline moving by asking the console
 * for the run, and must not hammer the console (it is throttled) or keep going once the run is over.
 *
 * Use cases:
 * - loads the run once; a run that is not moving gets no stream and no timers
 * - for a run that is moving, opens the stream and reloads on a slow beat so growing bars keep growing
 * - reloads soon after a progress event, and merges a burst of events into one load
 * - reloads straight away after an event that ends the run, and follows on until the run reads as over
 * - polls on a faster beat when the stream breaks or is refused
 * - stops the stream and the timers when the run turns out to be over, and when it is told to stop
 * - ignores a load that comes back after it was stopped
 * - keeps following after a load fails, and says so
 */
import { describe, expect, test } from "bun:test";

import { RunFollower, type FollowTimers } from "./run-follower";
import type { RunDetail, RunEvent, RunStatus } from "./types";

class FakeClock implements FollowTimers {
  time = 0;
  private next = 1;
  private pending = new Map<number, { at: number; fn: () => void }>();

  now() {
    return this.time;
  }
  setTimeout(fn: () => void, ms: number) {
    const id = this.next++;
    this.pending.set(id, { at: this.time + ms, fn });
    return id;
  }
  clearTimeout(handle: unknown) {
    this.pending.delete(handle as number);
  }
  get timers() {
    return this.pending.size;
  }
  /** Moves time on, running what falls due (and letting the loads they start finish) in order. */
  async advance(ms: number) {
    const end = this.time + ms;
    for (;;) {
      const due = [...this.pending.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      this.pending.delete(due[0]);
      this.time = due[1].at;
      due[1].fn();
      await settle();
    }
    this.time = end;
  }
}

const settle = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

const detail = (status: RunStatus): RunDetail => ({ id: "run-1", status }) as RunDetail;

function setup(statuses: (RunStatus | Error)[]) {
  const clock = new FakeClock();
  const seen: RunStatus[] = [];
  const errors: unknown[] = [];
  let loads = 0;
  let emit!: (event: RunEvent) => void;
  const stream = { closed: false, close() { this.closed = true; } };
  let opened = 0;
  const follower = new RunFollower({
    load: async () => {
      const next = statuses[Math.min(loads++, statuses.length - 1)];
      if (next instanceof Error) throw next;
      return detail(next);
    },
    onDetail: (d) => seen.push(d.status),
    onError: (e) => errors.push(e),
    open: (onEvent) => {
      opened++;
      emit = onEvent;
      return stream;
    },
    timers: clock,
  });
  return { follower, clock, seen, errors, stream, emit: (e: RunEvent) => emit(e), opened: () => opened, loads: () => loads };
}

const node: RunEvent = { name: "node", data: { node: "x", status: "running" } };
const done: RunEvent = { name: "done", data: { lesson_id: "l", stage: "ready" } };
const lost: RunEvent = { name: "error", data: { message: "Lost the connection to the server.", code: "connection" } };

describe("a run that is not moving", () => {
  test.each(["succeeded", "failed", "cancelled", "paused"] as const)("a %s run is loaded once, with no stream and no timers", async (status) => {
    const t = setup([status]);

    t.follower.start();
    await settle();

    expect([t.seen, t.opened(), t.clock.timers]).toEqual([[status], 0, 0]);
  });
});

describe("a run that is moving", () => {
  test("opens the stream after the first load and reloads on a slow beat", async () => {
    const t = setup(["running"]);

    t.follower.start();
    await settle();
    expect(t.opened()).toBe(1);
    await t.clock.advance(RunFollower.TICK_MS);

    expect(t.loads()).toBe(2);
  });

  test("reloads soon after a progress event, and merges a burst of events into one load", async () => {
    const t = setup(["running"]);
    t.follower.start();
    await settle();
    await t.clock.advance(RunFollower.MIN_GAP_MS);
    const before = t.loads();

    t.emit(node);
    t.emit(node);
    t.emit(node);
    await t.clock.advance(RunFollower.MIN_GAP_MS);

    expect(t.loads() - before).toBe(1);
  });

  test("does not reload more often than the minimum gap, however many events arrive", async () => {
    const t = setup(["running"]);
    t.follower.start();
    await settle();
    const before = t.loads();

    t.emit(node);
    await t.clock.advance(RunFollower.MIN_GAP_MS - 1);

    expect(t.loads()).toBe(before);
  });

  test("reloads straight away after an event that ends the run, and follows on until the run reads as over", async () => {
    const t = setup(["running", "running", "succeeded"]);
    t.follower.start();
    await settle();
    await t.clock.advance(RunFollower.MIN_GAP_MS);

    t.emit(done);
    await t.clock.advance(0);
    expect(t.seen.at(-1)).toBe("running"); // the database had not caught up with the event yet

    await t.clock.advance(RunFollower.POLL_MS);
    expect(t.seen.at(-1)).toBe("succeeded");
    expect(t.clock.timers).toBe(0);
  });

  test("closes the stream and stops the timers when a reload shows the run is over", async () => {
    const t = setup(["running", "failed"]);
    t.follower.start();
    await settle();

    await t.clock.advance(RunFollower.TICK_MS);

    expect([t.seen, t.stream.closed, t.clock.timers]).toEqual([["running", "failed"], true, 0]);
  });
});

describe("a stream that breaks", () => {
  test("polls on the faster beat instead, and does not open the stream again", async () => {
    const t = setup(["running"]);
    t.follower.start();
    await settle();

    t.emit(lost);
    await t.clock.advance(RunFollower.POLL_MS * 3);

    expect(t.loads()).toBe(1 + 3);
    expect(t.opened()).toBe(1);
  });
});

describe("stopping", () => {
  test("closes the stream and clears the timers", async () => {
    const t = setup(["running"]);
    t.follower.start();
    await settle();

    t.follower.stop();
    await t.clock.advance(RunFollower.TICK_MS * 2);

    expect([t.stream.closed, t.clock.timers, t.loads()]).toEqual([true, 0, 1]);
  });

  test("ignores a load that comes back after it was stopped", async () => {
    const t = setup(["running"]);

    t.follower.start();
    t.follower.stop();
    await settle();

    expect([t.seen, t.opened()]).toEqual([[], 0]);
  });
});

describe("a load that fails", () => {
  test("is reported, and the follower tries again on the fast beat", async () => {
    const boom = new Error("boom");
    const t = setup(["running", boom, "running"]);
    t.follower.start();
    await settle();

    await t.clock.advance(RunFollower.TICK_MS); // the slow beat's load fails
    await t.clock.advance(RunFollower.POLL_MS);

    expect(t.errors).toEqual([boom]);
    expect(t.seen).toEqual(["running", "running"]);
  });

  test("on the very first load still reports and tries again", async () => {
    const t = setup([new Error("boom"), "running"]);

    t.follower.start();
    await settle();
    await t.clock.advance(RunFollower.POLL_MS);

    expect([t.errors.length, t.seen]).toEqual([1, ["running"]]);
  });
});
