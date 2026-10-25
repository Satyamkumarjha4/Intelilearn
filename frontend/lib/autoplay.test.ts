/**
 * Unit under test: `Autoplay`, the timer and pause rules behind the "Three ways forward" carousel.
 *
 * Why: the carousel moves on by itself every six seconds, which is only welcome if it never moves under a hand or a
 * cursor, never runs while nobody can see it, and never fights a visitor who has just chosen a slide. Those rules are
 * easy to get subtly wrong (a pause that forgets how long it had run, a touch that never lets go), so they live here
 * where they can be tested against a clock that the test moves.
 *
 * Use cases:
 * - it does nothing until it is enabled, then advances every six seconds, looping
 * - a pause (hover, keyboard focus, touch, off screen) stops it, and letting go carries on with the time that was left
 * - it runs only when every pause has been let go of
 * - a touch pauses it, and four seconds after the finger lifts it carries on; a new touch in that time cancels that
 * - restarting (the visitor chose a slide) gives the next slide a full six seconds, also when it is paused at the time
 * - switching it off (reduced motion) stops it for good, and switching it on starts a fresh six seconds
 * - it reports when it becomes paused or running again, so the progress bar can pause with it
 * - disposing it stops everything
 */
import { describe, expect, test } from "bun:test";

import { Autoplay, type Clock } from "./autoplay";

class FakeClock implements Clock {
  time = 0;
  private timers = new Map<number, { at: number; run: () => void }>();
  private next = 1;

  now = () => this.time;
  set = (run: () => void, ms: number) => {
    this.timers.set(this.next, { at: this.time + ms, run });
    return this.next++;
  };
  clear = (handle: unknown) => void this.timers.delete(handle as number);
  get pending() {
    return this.timers.size;
  }

  /** Move time on, running what falls due on the way, in order. */
  tick(ms: number) {
    const end = this.time + ms;
    for (;;) {
      const due = [...this.timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      this.timers.delete(due[0]);
      this.time = due[1].at;
      due[1].run();
    }
    this.time = end;
  }
}

function make(enabled = true) {
  const clock = new FakeClock();
  const log = { advances: 0, paused: [] as boolean[] };
  const autoplay = new Autoplay(() => void log.advances++, (paused) => log.paused.push(paused), clock);
  if (enabled) autoplay.setEnabled(true);
  return { autoplay, clock, log };
}

describe("Autoplay", () => {
  test("does nothing until it is enabled, then advances every six seconds, looping", () => {
    const { autoplay, clock, log } = make(false);
    clock.tick(60_000);
    expect(log.advances).toBe(0);

    autoplay.setEnabled(true);
    clock.tick(5_999);
    expect(log.advances).toBe(0);
    clock.tick(1);
    expect(log.advances).toBe(1);
    clock.tick(6_000);
    clock.tick(6_000);
    expect(log.advances).toBe(3);
  });

  test("a pause stops it, and letting go carries on with the time that was left", () => {
    const { autoplay, clock, log } = make();
    clock.tick(4_000);
    autoplay.hold("hover");
    clock.tick(60_000);
    expect(log.advances).toBe(0);

    autoplay.release("hover");
    clock.tick(1_999);
    expect(log.advances).toBe(0);
    clock.tick(1);
    expect(log.advances).toBe(1);
  });

  test("it runs only when every pause has been let go of", () => {
    const { autoplay, clock, log } = make();
    autoplay.hold("hover");
    autoplay.hold("focus");
    autoplay.hold("hidden");

    autoplay.release("hover");
    autoplay.release("focus");
    clock.tick(60_000);
    expect(log.advances).toBe(0);
    expect(autoplay.running).toBe(false);

    autoplay.release("hidden");
    expect(autoplay.running).toBe(true);
    clock.tick(6_000);
    expect(log.advances).toBe(1);
  });

  test("holding the same pause twice, or letting go of one never held, changes nothing", () => {
    const { autoplay, clock, log } = make();
    autoplay.hold("hover");
    autoplay.hold("hover");
    autoplay.release("focus");
    autoplay.release("hover");

    clock.tick(6_000);
    expect(log.advances).toBe(1);
  });

  test("a touch pauses it, and four seconds after the finger lifts it carries on", () => {
    const { autoplay, clock, log } = make();
    clock.tick(1_000);
    autoplay.touchStart();
    clock.tick(30_000);
    expect(log.advances).toBe(0);

    autoplay.touchEnd();
    clock.tick(3_999);
    expect(autoplay.paused).toBe(true);
    clock.tick(1);
    expect(autoplay.paused).toBe(false);
    clock.tick(5_000); // the five seconds that were left
    expect(log.advances).toBe(1);
  });

  test("a new touch within those four seconds cancels the resume", () => {
    const { autoplay, clock, log } = make();
    autoplay.touchStart();
    autoplay.touchEnd();
    clock.tick(3_000);
    autoplay.touchStart();
    clock.tick(30_000);

    expect(autoplay.paused).toBe(true);
    expect(log.advances).toBe(0);
  });

  test("restarting gives the next slide a full six seconds", () => {
    const { autoplay, clock, log } = make();
    clock.tick(5_000);
    autoplay.restart();

    clock.tick(5_999);
    expect(log.advances).toBe(0);
    clock.tick(1);
    expect(log.advances).toBe(1);
  });

  test("restarting while paused also resets the time, and the full six seconds start when the pause ends", () => {
    const { autoplay, clock, log } = make();
    clock.tick(5_000);
    autoplay.hold("hover");
    autoplay.restart();
    clock.tick(30_000);
    expect(log.advances).toBe(0);

    autoplay.release("hover");
    clock.tick(5_999);
    expect(log.advances).toBe(0);
    clock.tick(1);
    expect(log.advances).toBe(1);
  });

  test("switching it off stops it for good, and on again starts a fresh six seconds", () => {
    const { autoplay, clock, log } = make();
    clock.tick(5_000);
    autoplay.setEnabled(false);
    clock.tick(60_000);
    expect(log.advances).toBe(0);
    expect(clock.pending).toBe(0);

    autoplay.setEnabled(true);
    clock.tick(5_999);
    expect(log.advances).toBe(0);
    clock.tick(1);
    expect(log.advances).toBe(1);
  });

  test("it reports when it becomes paused or running again, and only then", () => {
    const { autoplay, log } = make();
    autoplay.hold("hover");
    autoplay.hold("focus"); // already paused
    autoplay.release("hover");
    autoplay.release("focus");

    expect(log.paused).toEqual([true, false]);
  });

  test("disposing it stops everything", () => {
    const { autoplay, clock, log } = make();
    autoplay.touchStart();
    autoplay.touchEnd();
    autoplay.dispose();
    clock.tick(60_000);

    expect(clock.pending).toBe(0);
    expect(log.advances).toBe(0);
  });
});
