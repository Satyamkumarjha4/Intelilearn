/**
 * Unit under test: `ProgressExample`, the example data in the landing page's "Your tries" chart.
 *
 * Why: the chart is an example, not anyone's results, and says so; but its words must still agree with its bars, so the
 * "up N points" badge, the chart's label for a screen reader and the "best" tag are all worked out from the three scores.
 *
 * Use cases:
 * - the gain is the last score minus the one before it
 * - the label has one entry per attempt, in order, each with its own score
 * - exactly one caption names the best try, and it is the highest score
 */
import { describe, expect, test } from "bun:test";

import { ProgressExample } from "./progress-example";

describe("ProgressExample", () => {
  test("the gain is the last score minus the one before", () => {
    expect(ProgressExample.gain).toBe(ProgressExample.TRIES[2] - ProgressExample.TRIES[1]);
    expect(ProgressExample.gain).toBeGreaterThan(0);
  });

  test("the label has one entry per attempt, in order, each with its own score", () => {
    const entries = ProgressExample.label.match(/attempt \d+[^;]*/g) ?? [];

    expect(entries).toHaveLength(ProgressExample.TRIES.length);
    ProgressExample.TRIES.forEach((score, index) => {
      expect(entries[index]).toContain(`attempt ${index + 1}`);
      expect(entries[index]).toMatch(new RegExp(`\\b${score}\\b`));
    });
  });

  test("exactly one caption names the best try, and it is the highest score", () => {
    const captions = ProgressExample.TRIES.map((_, i) => ProgressExample.caption(i));
    const best = captions.flatMap((caption, i) => (/best/i.test(caption) ? [i] : []));

    expect(best).toEqual([ProgressExample.TRIES.indexOf(Math.max(...ProgressExample.TRIES))]);
    captions.forEach((caption, i) => expect(caption).toContain(String(i + 1)));
  });
});
