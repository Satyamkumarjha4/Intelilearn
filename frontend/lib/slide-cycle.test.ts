/**
 * Unit under test: `SlideCycle`, the arithmetic behind the "Three ways forward" carousel.
 *
 * Why: the carousel is moved three ways (tabs, arrows and keys, and the visitor's own swipe). Swipes only tell us a
 * scroll position, so the slide it landed on has to be worked out the same way the track lays slides out, and the
 * arrows must wrap rather than stop.
 *
 * Use cases:
 * - previous and next wrap around the ends
 * - a scroll position becomes the nearest slide, counting the gap between slides
 * - a position past either end is held to the first or last slide
 * - a track with no width, or no slides, is slide 0
 * - the arrow keys move to the next or previous slide, and no other key moves anything
 */
import { describe, expect, test } from "bun:test";

import { SlideCycle } from "./slide-cycle";

describe("SlideCycle", () => {
  test("next and previous wrap", () => {
    expect([SlideCycle.next(0, 3), SlideCycle.next(2, 3)]).toEqual([1, 0]);
    expect([SlideCycle.previous(2, 3), SlideCycle.previous(0, 3)]).toEqual([1, 2]);
  });

  test.each([
    [0, 0],
    [150, 0],
    [320, 1],
    [(300 + 16) * 2, 2],
  ])("a scroll of %ipx on 300px slides with a 16px gap is slide %i", (left, slide) => {
    expect(SlideCycle.fromScroll(left, 300, 16, 3)).toBe(slide);
  });

  test("a position past either end is held to the first or last slide", () => {
    expect(SlideCycle.fromScroll(-50, 300, 16, 3)).toBe(0);
    expect(SlideCycle.fromScroll(5000, 300, 16, 3)).toBe(2);
  });

  test("a track without width, or without slides, is slide 0", () => {
    expect(SlideCycle.fromScroll(100, 0, 16, 3)).toBe(0);
    expect(SlideCycle.fromScroll(100, 300, 16, 0)).toBe(0);
    expect(SlideCycle.next(0, 0)).toBe(0);
  });
});

describe("byKey", () => {
  test("the right arrow goes on and the left arrow goes back, wrapping", () => {
    expect(SlideCycle.byKey("ArrowRight", 2, 3)).toBe(0);
    expect(SlideCycle.byKey("ArrowLeft", 0, 3)).toBe(2);
    expect(SlideCycle.byKey("ArrowRight", 0, 3)).toBe(1);
  });

  test.each(["ArrowUp", "ArrowDown", "Tab", "Enter", " ", "a"])("%j moves nothing", (key) => {
    expect(SlideCycle.byKey(key, 1, 3)).toBeNull();
  });
});
