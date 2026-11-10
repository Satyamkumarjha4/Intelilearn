/**
 * Unit under test: `ProgressExample`, the example data in the landing page's "Your tries" chart.
 *
 * Why: the chart is an example, not anyone's results, and says so; but its words must still agree with its bars, so the
 * "up N points" badge, the chart's label for a screen reader and the "best" tag are all worked out from the three scores.
 *
 * Use cases:
 * - the gain is the last score minus the one before it
 * - the label names each attempt and its score in order
 * - the best try is named in its caption and the others are not
 */
import { describe, expect, test } from "bun:test";

import { ProgressExample } from "./progress-example";

describe("ProgressExample", () => {
  test("the gain is the last score minus the one before", () => {
    expect(ProgressExample.gain).toBe(ProgressExample.TRIES[2] - ProgressExample.TRIES[1]);
    expect(ProgressExample.gain).toBeGreaterThan(0);
  });

  test("the label names each attempt and its score", () => {
    expect(ProgressExample.label).toBe("Example scores: attempt 1, 45 percent; attempt 2, 62 percent; attempt 3, 85 percent");
  });

  test("only the best try is named in its caption", () => {
    expect([0, 1, 2].map((i) => ProgressExample.caption(i))).toEqual(["Try 1", "Try 2", "Try 3 · best"]);
  });
});
