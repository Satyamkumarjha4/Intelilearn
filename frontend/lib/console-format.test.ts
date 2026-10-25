/**
 * Unit under test: `ConsoleFormat`, how the console writes money, call times, counts, percentages and changes.
 *
 * Why: the same figure appears in tiles, tables, tooltips and exports. If one page rounded a cheap call to "$0.00" or
 * wrote "3,9 s" while another wrote "3.9 s", the numbers would look like they disagreed, and a delta that divides by
 * zero would show "Infinity%" to someone deciding whether Socra is fine.
 *
 * Use cases:
 * - money in US dollars: cents above a cent, four places below it, thousands separated, zero and missing handled,
 *   decimal strings from the API accepted, a whole-dollar form for budgets and a short form for chart axes
 * - call times from milliseconds to hours, rounded so that "60 s" never appears
 * - counts with separators, and compact token counts (k, M)
 * - percentages, and a share of a whole that is safe when the whole is zero
 * - a percentage change: signed, rounded, "new" from nothing, nothing to say when both are zero
 * - a change in points between two percentages, and nothing when one is missing
 * - what a change is compared with, range labels and short dates (UTC days)
 * - axis labels for call times: whole numbers without a decimal, seconds then minutes
 */
import { describe, expect, test } from "bun:test";

import { ConsoleFormat } from "./console-format";

describe("ConsoleFormat.money", () => {
  test.each([
    ["3.84", "$3.84"],
    [3.8449, "$3.84"],
    ["0.035000", "$0.04"],
    ["0.0042", "$0.0042"],
    ["0.000001", "<$0.0001"],
    [0, "$0.00"],
    ["0.000000", "$0.00"],
    [1234.5, "$1,235"],
    [999.994, "$999.99"],
    [-2.5, "−$2.50"],
  ])("%p is %s", (value, expected) => {
    expect(ConsoleFormat.money(value)).toBe(expected);
  });

  test.each([null, undefined, "", "abc"])("%p is a dash", (value) => {
    expect(ConsoleFormat.money(value as never)).toBe("–");
  });

  test("a whole number of dollars drops the cents", () => {
    expect(ConsoleFormat.moneyShort("25.000000")).toBe("$25");
    expect(ConsoleFormat.moneyShort("11.2")).toBe("$11.20");
    expect(ConsoleFormat.moneyShort(null)).toBe("\u2013");
  });

  test("axis labels drop trailing zeros", () => {
    expect([0, 0.5, 1, 12, 0.25].map(ConsoleFormat.moneyAxis)).toEqual(["$0", "$0.5", "$1", "$12", "$0.25"]);
  });
});

describe("ConsoleFormat.duration", () => {
  test.each([
    [0.42, "420 ms"],
    [0, "0 ms"],
    [3.94, "3.9 s"],
    [9.96, "10.0 s"],
    [41.2, "41 s"],
    [59.6, "1 min"],
    [60, "1 min"],
    [125, "2 min 5 s"],
    [3600, "1 h"],
    [3900, "1 h 5 min"],
  ])("%p s is %s", (seconds, expected) => {
    expect(ConsoleFormat.duration(seconds)).toBe(expected);
  });

  test.each([null, undefined, Number.NaN])("%p is a dash", (value) => {
    expect(ConsoleFormat.duration(value as never)).toBe("–");
  });
});

describe("counts and percentages", () => {
  test("counts have separators", () => {
    expect(ConsoleFormat.count(1476)).toBe("1,476");
    expect(ConsoleFormat.count(12.6)).toBe("13");
  });

  test.each([
    [950, "950"],
    [3300, "3.3k"],
    [4_100_000, "4.1M"],
    [10_000, "10k"],
    [999_999, "1M"],
  ])("%p tokens is %s", (value, expected) => {
    expect(ConsoleFormat.compact(value)).toBe(expected);
  });

  test("percent trims zeros", () => {
    expect(ConsoleFormat.percent(87)).toBe("87%");
    expect(ConsoleFormat.percent(86.96, 1)).toBe("87%");
    expect(ConsoleFormat.percent(86.94, 1)).toBe("86.9%");
  });

  test("a share of nothing is zero, not NaN", () => {
    expect(ConsoleFormat.ratio(1284, 1476)).toBeCloseTo(86.99, 1);
    expect(ConsoleFormat.ratio(0, 0)).toBe(0);
    expect(ConsoleFormat.ratio(5, 0)).toBe(0);
  });
});

describe("changes", () => {
  test.each([
    [56, 50, { label: "+12%", direction: "up" }],
    [45, 50, { label: "−10%", direction: "down" }],
    [50, 50, { label: "0%", direction: "flat" }],
    [50.2, 50, { label: "0%", direction: "flat" }],
    [3, 0, { label: "new", direction: "up" }],
  ])("%p against %p", (current, previous, expected) => {
    expect(ConsoleFormat.percentDelta(current, previous)).toEqual(expected as never);
  });

  test("nothing to compare when both are zero", () => {
    expect(ConsoleFormat.percentDelta(0, 0)).toBeNull();
  });

  test("a drop to nothing is minus 100%", () => {
    expect(ConsoleFormat.percentDelta(0, 8)).toEqual({ label: "−100%", direction: "down" });
  });

  test.each([
    [65, 70, { label: "−5 pts", direction: "down" }],
    [70.4, 65, { label: "+5 pts", direction: "up" }],
    [65, 65.2, { label: "0 pts", direction: "flat" }],
  ])("points %p against %p", (current, previous, expected) => {
    expect(ConsoleFormat.pointsDelta(current, previous)).toEqual(expected as never);
  });

  test("points need both figures", () => {
    expect(ConsoleFormat.pointsDelta(null, 60)).toBeNull();
    expect(ConsoleFormat.pointsDelta(60, null)).toBeNull();
  });

  test("says what a change is against", () => {
    expect(ConsoleFormat.versus("today")).toBe("vs yesterday");
    expect(ConsoleFormat.versus("7d")).toBe("vs previous 7 days");
    expect(ConsoleFormat.versus("30d")).toBe("vs previous 30 days");
  });
});

describe("labels and dates", () => {
  test("range labels", () => {
    expect((["today", "7d", "30d", "custom"] as const).map(ConsoleFormat.rangeLabel)).toEqual(["Today", "7 days", "30 days", "Custom"]);
  });

  test("days are UTC days, from a date or a time", () => {
    expect(ConsoleFormat.day("2026-03-15")).toBe("15 Mar");
    expect(ConsoleFormat.day("2026-03-15T23:30:00Z")).toBe("15 Mar");
    expect(ConsoleFormat.dayLong("2026-03-15")).toBe("Sun 15 Mar");
    expect(ConsoleFormat.day("nonsense")).toBe("");
  });
});

describe("ConsoleFormat.durationAxis", () => {
  test.each([
    [0, "0"],
    [5, "5 s"],
    [2.5, "2.5 s"],
    [30, "30 s"],
    [60, "1 min"],
    [90, "1.5 min"],
    [600, "10 min"],
  ])("%p seconds is %p", (seconds, text) => {
    expect(ConsoleFormat.durationAxis(seconds)).toBe(text);
  });
});
