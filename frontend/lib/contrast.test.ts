/**
 * Unit under test: `Oklch` (`lib/contrast.ts`), the WCAG contrast of the design tokens' `oklch()` colours.
 *
 * Why: the primary-button contrast test (`primary-button-contrast.test.ts`) is only as good as this arithmetic, so it
 * is checked against pairs whose ratio is known.
 *
 * Use cases:
 * - black on white is 21:1 and a colour against itself is 1:1, in either order
 * - a mid grey on white matches the published ratio (about 4.5:1 for #767676)
 * - `hex()` writes the colour a browser would paint
 * - anything that is not `oklch(L C h)` is refused
 */
import { describe, expect, test } from "bun:test";
import { Oklch } from "./contrast";

const black = Oklch.parse("oklch(0 0 0)");
const white = Oklch.parse("oklch(1 0 0)");

describe("Oklch", () => {
  test("black on white is 21:1, white on white 1:1, in either order", () => {
    expect(Oklch.contrast(black, white)).toBeCloseTo(21, 1);
    expect(Oklch.contrast(white, black)).toBeCloseTo(21, 1);
    expect(Oklch.contrast(white, white)).toBe(1);
  });

  test("a mid grey on white matches the published ratio", () => {
    const grey = Oklch.parse("oklch(0.5681 0 0)"); // #767676
    expect(Oklch.contrast(grey, white)).toBeCloseTo(4.5, 0);
  });

  test("hex() writes the painted colour", () => {
    expect(white.hex()).toBe("#FFFFFF");
    expect(black.hex()).toBe("#000000");
    expect(Oklch.parse("oklch(0.5681 0 0)").hex()).toBe("#777777"); // the nearest whole step
  });

  test("anything but oklch(L C h) is refused", () => {
    expect(() => Oklch.parse("#0B6E77")).toThrow();
    expect(() => Oklch.parse("oklch(0.5 0.1)")).toThrow();
    expect(() => Oklch.parse("var(--primary)")).toThrow();
  });
});
