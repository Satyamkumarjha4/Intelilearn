/**
 * Unit under test: `RoundedRect`, the outline of a bar segment in the console's charts.
 *
 * Why: in a stacked bar only the outer segment may be rounded, or the stack looks like separate pills and the
 * proportions are hard to read. A radius larger than the bar, or a zero-size segment, must not draw a broken shape.
 *
 * Use cases:
 * - a segment with no rounding is a plain rectangle
 * - the top segment of a column has its two top corners rounded; the end segment of a row, its two right corners
 * - a radius is limited to half the width and to the height, so a thin bar stays a valid shape
 * - a segment with no width or height has no outline
 */
import { describe, expect, test } from "bun:test";

import { RoundedRect } from "./chart-shapes";

describe("RoundedRect.path", () => {
  test("plain", () => {
    expect(RoundedRect.path(10, 20, 30, 40, 6, "none")).toBe("M10 20 H40 V60 H10 Z");
  });

  test("a column's top segment is rounded at the top", () => {
    expect(RoundedRect.path(10, 20, 30, 40, 6, "top")).toBe("M10 60 V26 A6 6 0 0 1 16 20 H34 A6 6 0 0 1 40 26 V60 Z");
  });

  test("a row's end segment is rounded at the right", () => {
    expect(RoundedRect.path(10, 20, 40, 30, 6, "right")).toBe("M10 20 H44 A6 6 0 0 1 50 26 V44 A6 6 0 0 1 44 50 H10 Z");
  });

  test("the radius never exceeds half the width or the height", () => {
    expect(RoundedRect.path(0, 0, 4, 40, 10, "top")).toBe("M0 40 V2 A2 2 0 0 1 2 0 H2 A2 2 0 0 1 4 2 V40 Z");
    expect(RoundedRect.path(0, 0, 40, 3, 10, "right")).toBe("M0 0 H38.5 A1.5 1.5 0 0 1 40 1.5 V1.5 A1.5 1.5 0 0 1 38.5 3 H0 Z");
    expect(RoundedRect.path(0, 0, 40, 3, 10, "top")).toBe("M0 3 V3 A3 3 0 0 1 3 0 H37 A3 3 0 0 1 40 3 V3 Z");
  });

  test.each([
    [0, 10],
    [10, 0],
    [-5, 10],
    [Number.NaN, 10],
  ])("size %p by %p has no outline", (width, height) => {
    expect(RoundedRect.path(0, 0, width, height, 6, "top")).toBe("");
  });
});
