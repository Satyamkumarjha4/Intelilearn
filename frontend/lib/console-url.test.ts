/**
 * Unit under test: `ConsoleUrl`, the console pages' state in the address bar.
 *
 * Why: filters in the URL are what make a view shareable ("look at the failing Gemini calls last week"). A hand-edited
 * or stale link must not break the page, and a custom range that the API would refuse (backwards, over a year, not a
 * date) must never be sent.
 *
 * Use cases:
 * - the overview reads `?range=` and falls back to 7 days for anything else; it writes nothing for the default
 * - the usage page reads range, custom dates, provider, model, step and outcome, trimmed
 * - an unknown outcome or range, and a custom range without good dates, fall back to the defaults
 * - dates must be real, in order and within a year
 * - writing leaves out the defaults and the dates of a range that is not custom, and reading it back gives the same filters
 * - choosing a range drops the dates, except that custom starts as the last 7 days
 */
import { describe, expect, test } from "bun:test";

import { ConsoleUrl } from "./console-url";

const params = (query: string) => new URLSearchParams(query);

describe("overview range", () => {
  test.each([
    ["range=today", "today"],
    ["range=30d", "30d"],
    ["range=7d", "7d"],
    ["", "7d"],
    ["range=yesterday", "7d"],
    ["range=custom", "7d"],
  ])("%p reads as %s", (query, expected) => {
    expect(ConsoleUrl.overviewRange(params(query))).toBe(expected as never);
  });

  test("writes nothing for the default", () => {
    expect(ConsoleUrl.overviewQuery("7d")).toBe("");
    expect(ConsoleUrl.overviewQuery("today")).toBe("?range=today");
    expect(ConsoleUrl.overviewQuery("30d")).toBe("?range=30d");
  });
});

describe("usage filters", () => {
  test("reads every filter", () => {
    const filters = ConsoleUrl.usageFilters(params("range=30d&provider=groq&model=openai%2Fgpt-oss-120b&node=page.generate&outcome=retried"));

    expect(filters).toEqual({ range: "30d", provider: "groq", model: "openai/gpt-oss-120b", node: "page.generate", outcome: "retried" });
  });

  test("an empty address is the defaults", () => {
    expect(ConsoleUrl.usageFilters(params(""))).toEqual({ range: "7d", provider: "", model: "", node: "", outcome: "" });
  });

  test("trims, and drops an outcome that does not exist", () => {
    const filters = ConsoleUrl.usageFilters(params("provider=%20groq%20&outcome=slow"));

    expect(filters.provider).toBe("groq");
    expect(filters.outcome).toBe("");
  });

  test("reads a custom range with its dates", () => {
    const filters = ConsoleUrl.usageFilters(params("range=custom&start=2026-03-01&end=2026-03-10"));

    expect(filters).toMatchObject({ range: "custom", start: "2026-03-01", end: "2026-03-10" });
  });

  test.each([
    "range=custom",
    "range=custom&start=2026-03-01",
    "range=custom&start=2026-03-10&end=2026-03-01",
    "range=custom&start=2024-01-01&end=2026-03-01",
    "range=custom&start=2026-02-30&end=2026-03-10",
    "range=custom&start=yesterday&end=today",
    "range=bogus",
  ])("%s falls back to 7 days", (query) => {
    const filters = ConsoleUrl.usageFilters(params(query));

    expect(filters.range).toBe("7d");
    expect(filters.start).toBeUndefined();
    expect(filters.end).toBeUndefined();
  });

  test("dates without custom are ignored", () => {
    expect(ConsoleUrl.usageFilters(params("range=today&start=2026-03-01&end=2026-03-10"))).toEqual({
      range: "today", provider: "", model: "", node: "", outcome: "",
    });
  });
});

describe("dates", () => {
  test.each([
    ["2026-03-01", "2026-03-01", true],
    ["2026-03-01", "2026-03-10", true],
    ["2026-03-10", "2026-03-01", false],
    ["2025-03-01", "2026-03-01", true], // 366 days
    ["2025-02-28", "2026-03-01", false],
    ["2026-13-01", "2026-13-02", false],
    ["2026-3-1", "2026-3-10", false],
  ])("%s to %s is %p", (start, end, ok) => {
    expect(ConsoleUrl.validDays(start, end)).toBe(ok);
  });

  test("formats the UTC day", () => {
    expect(ConsoleUrl.isoDay(new Date("2026-03-15T23:59:00Z"))).toBe("2026-03-15");
  });
});

describe("usage query", () => {
  test("is empty for the defaults", () => {
    expect(ConsoleUrl.usageQuery({ range: "7d", provider: "", model: "", node: "", outcome: "" })).toBe("");
    expect(ConsoleUrl.usageQuery({})).toBe("");
  });

  test("writes only what is set, and the dates only for custom", () => {
    expect(ConsoleUrl.usageQuery({ range: "30d", provider: "groq", start: "2026-03-01", end: "2026-03-10", outcome: "failed" })).toBe(
      "?range=30d&provider=groq&outcome=failed",
    );
    expect(ConsoleUrl.usageQuery({ range: "custom", start: "2026-03-01", end: "2026-03-10", node: "page.generate" })).toBe(
      "?range=custom&start=2026-03-01&end=2026-03-10&node=page.generate",
    );
  });

  test("reads back what it wrote", () => {
    const filters = { range: "custom" as const, start: "2026-03-01", end: "2026-03-10", provider: "groq", model: "m/x y", node: "", outcome: "ok" as const };

    expect(ConsoleUrl.usageFilters(params(ConsoleUrl.usageQuery(filters)))).toEqual(filters);
  });
});

describe("choosing a range", () => {
  const today = new Date("2026-03-15T08:00:00Z");

  test("a plain range drops the dates and keeps the other filters", () => {
    const next = ConsoleUrl.withRange({ range: "custom", start: "2026-03-01", end: "2026-03-10", provider: "groq" }, "30d", today);

    expect(next).toEqual({ range: "30d", start: undefined, end: undefined, provider: "groq" });
  });

  test("custom starts as the last 7 days", () => {
    expect(ConsoleUrl.withRange({ range: "7d" }, "custom", today)).toMatchObject({ range: "custom", start: "2026-03-09", end: "2026-03-15" });
  });

  test("custom keeps dates it already has", () => {
    const filters = { range: "custom" as const, start: "2026-03-01", end: "2026-03-10" };

    expect(ConsoleUrl.withRange(filters, "custom", today)).toMatchObject({ start: "2026-03-01", end: "2026-03-10" });
  });
});
