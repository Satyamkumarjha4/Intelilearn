/**
 * Unit under test: `Walkthrough`, the state of the "How it works" steps.
 *
 * Why: the steps play on their own, one every five seconds, until the visitor takes over by clicking one. If clicking
 * did not stop the autoplay, the stage would change under their hand; if the last step did not wrap, it would stall.
 *
 * Use cases:
 * - starts on the first step, playing by default (or not, when asked)
 * - advancing goes to the next step and wraps from the last to the first, still playing
 * - choosing a step shows it and stops the autoplay for good
 * - choosing a step that does not exist is held to the nearest real one
 * - stepping by a direction (the arrow keys) wraps both ways and stops the autoplay
 */
import { describe, expect, test } from "bun:test";

import { Walkthrough } from "./walkthrough";

describe("Walkthrough", () => {
  test("starts on the first step, playing", () => {
    const walk = Walkthrough.start(4);

    expect([walk.index, walk.autoplay]).toEqual([0, true]);
    expect(Walkthrough.start(4, false).autoplay).toBe(false);
  });

  test("advancing goes on, wraps at the end and keeps playing", () => {
    let walk = Walkthrough.start(4);
    const seen = [walk.index];
    for (let n = 0; n < 4; n++) {
      walk = walk.advance();
      seen.push(walk.index);
    }

    expect(seen).toEqual([0, 1, 2, 3, 0]);
    expect(walk.autoplay).toBe(true);
  });

  test("choosing a step shows it and stops the autoplay for good", () => {
    const walk = Walkthrough.start(4).choose(2);

    expect([walk.index, walk.autoplay]).toEqual([2, false]);
    expect(walk.advance().autoplay).toBe(false);
  });

  test.each([[-3, 0], [9, 3]])("choosing step %i is held to step %i", (asked, held) => {
    expect(Walkthrough.start(4).choose(asked).index).toBe(held);
  });

  test("stepping by a direction wraps both ways and stops the autoplay", () => {
    expect(Walkthrough.start(4).step(-1).index).toBe(3);
    expect(Walkthrough.start(4).choose(3).step(1).index).toBe(0);
    expect(Walkthrough.start(4).step(1).autoplay).toBe(false);
  });
});
