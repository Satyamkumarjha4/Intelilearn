/**
 * Unit under test: `ResendClock`, the wait before "Send a new code" works again.
 *
 * Why: the server refuses a second code inside a minute. The button must not invite a press that will be refused, and when
 * the server says how long to wait (`Retry-After`), the button waits exactly that. Time is injected, so nothing sleeps.
 *
 * Use cases:
 * - after `start()` the button waits a minute and counts down in whole seconds (rounded up), then is ready
 * - a wait the server asked for replaces the minute; a missing, zero, negative or silly one falls back to a minute
 * - the label says how long is left, and plain words when ready
 * - before anything was started it is ready
 */
import { describe, expect, test } from "bun:test";

import { ResendClock } from "./resend-clock";

function clockAt() {
  let now = 1_000_000;
  const clock = new ResendClock(() => now);
  return { clock, move: (ms: number) => (now += ms) };
}

describe("the countdown", () => {
  test("a minute, counting down in whole seconds, rounded up", () => {
    const { clock, move } = clockAt();
    clock.start();

    expect(clock.remaining()).toBe(60);
    move(500);
    expect(clock.remaining()).toBe(60);
    move(1000);
    expect(clock.remaining()).toBe(59);
    move(57_500);
    expect(clock.remaining()).toBe(1);
    expect(clock.ready()).toBe(false);
    move(1000);
    expect(clock.remaining()).toBe(0);
    expect(clock.ready()).toBe(true);
  });

  test("the wait the server asked for replaces the minute", () => {
    const { clock } = clockAt();
    clock.start(12);

    expect(clock.remaining()).toBe(12);
  });

  test.each([[null], [0], [-5], [Number.NaN], [Number.POSITIVE_INFINITY]])("%p falls back to a minute", (seconds) => {
    const { clock } = clockAt();
    clock.start(seconds);

    expect(clock.remaining()).toBe(60);
  });

  test("before anything was started it is ready", () => {
    expect(clockAt().clock.ready()).toBe(true);
  });
});

describe("the label", () => {
  test("says how long is left, and plain words when ready", () => {
    const { clock, move } = clockAt();
    clock.start(30);

    expect(clock.label()).toBe("Send a new code in 30s");
    move(30_000);
    expect(clock.label()).toBe("Send a new code");
  });
});
