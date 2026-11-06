/**
 * Unit under test: `HistoryWords`, the credit history in a learner's words.
 *
 * Why: the history is a list of changes, newest first, that can run to hundreds of rows. A learner reads it by day and by
 * sign: credits in are good news, credits out are spending. The rows already read as sentences from the server; this
 * groups and signs them.
 *
 * Use cases:
 * - a change is drawn with its sign, a real minus, and zero as 0
 * - the tone follows the sign
 * - rows are grouped by day in the order given, with Today, Yesterday and a dated heading
 * - rows of one day stay together and in order; nothing is dropped
 * - an empty history has a friendly line
 */
import { describe, expect, test } from "bun:test";

import { HistoryWords } from "./history-words";
import type { Transaction } from "./types";

const row = (id: number, created: Date, amount = 1): Transaction => ({
  id, kind: "earned", text: `row ${id}`, amount, balance_after: 10, created_at: created.toISOString(), subject: null,
});

const NOW = new Date(2026, 10, 5, 15, 0);

test("a change is drawn with its sign", () => {
  expect(HistoryWords.amount(10)).toBe("+10");
  expect(HistoryWords.amount(-3)).toBe("−3");
  expect(HistoryWords.amount(0)).toBe("0");
});

test("the tone follows the sign", () => {
  expect([HistoryWords.tone(2), HistoryWords.tone(-2), HistoryWords.tone(0)]).toEqual(["gain", "spend", "none"]);
});

describe("by day", () => {
  test("groups rows in the order given with a heading for each day", () => {
    const days = HistoryWords.byDay(
      [row(5, new Date(2026, 10, 5, 14)), row(4, new Date(2026, 10, 5, 9)), row(3, new Date(2026, 10, 4, 20)), row(2, new Date(2026, 10, 1, 8))],
      NOW,
    );

    expect(days.map((d) => d.heading)).toEqual(["Today", "Yesterday", "Sun 1 Nov"]);
    expect(days.map((d) => d.rows.map((r) => r.id))).toEqual([[5, 4], [3], [2]]);
  });

  test("a day that comes back later in the list is a new group, because rows are not reordered", () => {
    const days = HistoryWords.byDay([row(3, new Date(2026, 10, 5, 9)), row(2, new Date(2026, 10, 4, 9)), row(1, new Date(2026, 10, 5, 8))], NOW);

    expect(days).toHaveLength(3);
  });

  test("an empty history has no days and a friendly line", () => {
    expect(HistoryWords.byDay([], NOW)).toEqual([]);
    expect(HistoryWords.EMPTY).toContain("Nothing here yet");
  });
});
