/**
 * Unit under test: `AttemptHistoryView` and `AttemptChart`, how a lesson's attempts are listed and drawn.
 *
 * Why: the history is how a learner sees whether trying again is working. "Up 30 points on last time" must be right in
 * both directions and at the first attempt, a time must read like a person would say it, an attempt that is not graded
 * yet must not show a score, and the small chart must keep the bars in proportion and mark the best one.
 *
 * Use cases:
 * - each graded attempt shows its marks, percent, band, how long it took and how it compares with the last attempt and
 *   with the best one so far; the newest is listed first
 * - the first attempt has nothing to compare with; a tie says "same as"; the best attempt is marked
 * - an attempt that is being prepared, in progress or being marked says so instead of a score
 * - a time is told in seconds, minutes and hours, and is empty when not known
 * - the chart has one bar for each graded attempt, tall in proportion to its percent, the best one marked, with room for
 *   zero and for a full score
 */
import { describe, expect, test } from "bun:test";

import { AttemptChart, AttemptHistoryView } from "./attempt-history";
import type { AttemptHistory, AttemptSummary, TrendPoint } from "./types";

const summary = (n: number, over: Partial<AttemptSummary> = {}): AttemptSummary => ({
  id: `A${n}`, attempt_no: n, status: "graded", awarded: 10, available: 20, percent: 50, band: "normal", duration_s: 125,
  submitted_at: "2026-10-30T10:00:00Z", ...over,
});
const point = (n: number, percent: number, previous: number | null, best: number | null): TrendPoint => ({
  attempt_no: n, awarded: percent / 5, available: 20, percent, delta_previous: previous, delta_best: best,
});

const history = (): AttemptHistory => ({
  attempts: [
    summary(1, { awarded: 10, percent: 50 }),
    summary(2, { awarded: 16, percent: 80, band: "normal", duration_s: 45 }),
    summary(3, { awarded: 12, percent: 60, band: "normal", duration_s: 3700 }),
    summary(4, { status: "in_progress", awarded: null, available: null, percent: null, band: "", duration_s: null, submitted_at: null }),
  ],
  trend: { series: [point(1, 50, null, null), point(2, 80, 30, 30), point(3, 60, -20, -20)], best_attempt_no: 2 },
});

describe("AttemptHistoryView.rows", () => {
  test("lists the newest attempt first, with its marks, percent and time", () => {
    const rows = AttemptHistoryView.rows(history());

    expect(rows.map((r) => r.attemptNo)).toEqual([4, 3, 2, 1]);
    expect(rows[2]).toMatchObject({ title: "Attempt 2", marks: "16 of 20", percentText: "80%", duration: "45 s", band: "Good" });
    expect(rows[1].duration).toBe("1 h 1 min");
  });

  test("compares each attempt with the last one and with the best so far", () => {
    const rows = AttemptHistoryView.rows(history());
    const byNo = Object.fromEntries(rows.map((r) => [r.attemptNo, r]));

    expect(byNo[1].changes).toEqual([]);
    expect(byNo[2].changes).toEqual(["Up 30 points on last time", "A new best"]);
    expect(byNo[3].changes).toEqual(["Down 20 points on last time", "20 points under your best"]);
  });

  test("marks the best attempt", () => {
    const rows = AttemptHistoryView.rows(history());

    expect(rows.filter((r) => r.best).map((r) => r.attemptNo)).toEqual([2]);
  });

  test("a tie with the last attempt says same as, and a tie with the best is not a new best", () => {
    const tied: AttemptHistory = {
      attempts: [summary(1, { percent: 80 }), summary(2, { percent: 80 })],
      trend: { series: [point(1, 80, null, null), point(2, 80, 0, 0)], best_attempt_no: 1 },
    };

    const second = AttemptHistoryView.rows(tied).find((r) => r.attemptNo === 2)!;

    expect(second.changes).toEqual(["Same as last time", "Level with your best"]);
  });

  test("an attempt that is not graded says what is happening instead of a score", () => {
    const rows = AttemptHistoryView.rows({
      attempts: [
        summary(1, { status: "generating", percent: null, awarded: null, available: null, band: "" }),
        summary(2, { status: "in_progress", percent: null, awarded: null, available: null, band: "" }),
        summary(3, { status: "grading", percent: null, awarded: null, available: null, band: "" }),
        summary(4, { status: "failed", percent: null, awarded: null, available: null, band: "" }),
      ],
      trend: { series: [], best_attempt_no: null },
    });

    expect(rows.map((r) => [r.attemptNo, r.percentText, r.marks, r.state])).toEqual([
      [4, "", "", "Needs marking again"],
      [3, "", "", "Being marked"],
      [2, "", "", "In progress"],
      [1, "", "", "Getting questions ready"],
    ]);
  });

  test("no attempts is no rows", () => {
    expect(AttemptHistoryView.rows({ attempts: [], trend: { series: [], best_attempt_no: null } })).toEqual([]);
  });
});

describe("AttemptHistoryView.duration", () => {
  test.each([
    [0, "0 s"], [45, "45 s"], [60, "1 min"], [125, "2 min 5 s"], [3600, "1 h"], [3700, "1 h 1 min"], [null, ""], [-5, ""],
  ])("%p is %p", (seconds, text) => {
    expect(AttemptHistoryView.duration(seconds)).toBe(text);
  });
});

describe("AttemptChart.bars", () => {
  const series = [point(1, 50, null, null), point(2, 80, 30, 30), point(3, 0, -80, -30), point(4, 100, 100, 20)];

  test("one bar for each graded attempt, tall in proportion to its percent", () => {
    const bars = AttemptChart.bars(series, 200, 100, 2);

    expect(bars).toHaveLength(4);
    expect(bars.map((b) => b.height)).toEqual([51, 80, 2, 100]);
    expect(bars.every((b) => b.width > 0 && b.y + b.height === 100)).toBe(true);
  });

  test("the bars are spread across the width in order and do not overlap", () => {
    const bars = AttemptChart.bars(series, 200, 100, 2);

    for (let i = 1; i < bars.length; i++) expect(bars[i].x).toBeGreaterThanOrEqual(bars[i - 1].x + bars[i - 1].width);
    expect(bars[0].x).toBeGreaterThanOrEqual(0);
    expect(bars.at(-1)!.x + bars.at(-1)!.width).toBeLessThanOrEqual(200);
  });

  test("labels each bar and marks the best", () => {
    const bars = AttemptChart.bars(series, 200, 100, 2, 4);

    expect(bars.map((b) => b.label)).toEqual(["Attempt 1: 50%", "Attempt 2: 80%", "Attempt 3: 0%", "Attempt 4: 100%"]);
    expect(bars.filter((b) => b.best).map((b) => b.attemptNo)).toEqual([4]);
  });

  test("each bar has an outline with a rounded top, and none when there is nothing to draw", () => {
    const [first] = AttemptChart.bars(series, 200, 100, 2);

    expect(first.path.startsWith("M")).toBe(true);
    expect(AttemptChart.bars([], 200, 100, 2)).toEqual([]);
  });
});
