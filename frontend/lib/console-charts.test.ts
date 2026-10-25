/**
 * Unit under test: `lib/console-charts.ts`, which turns the console API's replies into what the pages draw: provider
 * series, stacked spend, sparklines, the overview's tiles, health pills, attention buttons, the funnel, slow steps,
 * and the usage page's charts, tiles and table rows.
 *
 * Why: the components only draw. A provider that changes colour with its rank, a gap drawn as a zero, a tile that
 * divides by zero or a funnel that does not say where the lessons went would each mislead someone reading the numbers.
 *
 * Use cases:
 * - a provider keeps its colour and label whatever it spent; Gemini is Google, anything unknown is Other
 * - daily spend becomes one row per day, other providers add up into Other, only series that spent are listed, the top
 *   segment of a day is the last series with spend, and there is a table form
 * - a sparkline scales to its data, breaks at a gap, and is flat for a constant series
 * - the four overview tiles: started with a change and a daily line; finished as x / y with points and a meter; spend
 *   against the monthly budget (the meter turns warning, then danger); calls that worked with fallbacks
 * - empty periods say so instead of showing NaN or a change from nothing
 * - health pills show latency and worker count; attention items get a tone, a button label and the API's page
 * - the funnel gives each step's share of those started and says what became of the rest
 * - slowest steps get readable times; call time per model leaves out models that never worked
 * - outcome shares add up to the model's calls; step rows know their spend relative to the costliest
 * - the usage tiles: calls with the share that worked, tokens, spend split by provider, call times
 * - every chart explains a hovered mark: a day's spend per provider with the total, a step's share of those started, a
 *   step's p95, a model's median and p95, a model's worked / retried / failed counts
 * - the funnel and slowest steps have table forms
 * - a call-time bar is the median and its tick the p95, drawn inside one p95-long bar; a median above the p95 is capped
 * - the outcome chart's colours are the status colours, in a fixed order, and only its last segment is rounded
 * - provider colours and status colours never share a chart: the outcome chart (data and component) uses only status
 *   tokens, the spend and call-time charts only provider tokens, and the p95 tick and cursor are neutral
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  AttentionActions,
  ChartPalette,
  FunnelChart,
  HealthPills,
  LatencyChart,
  OutcomeChart,
  OverviewKpis,
  ProviderSeries,
  RangeWords,
  SlowestSteps,
  Sparkline,
  SpendChart,
  StepTable,
  UsageKpis,
} from "./console-charts";
import { ConsoleFormat } from "./console-format";
import type { ConsoleOverview, ConsoleUsage } from "./types";

function overview(patch: Partial<ConsoleOverview> = {}): ConsoleOverview {
  const up = { ok: true, latency_ms: 4, detail: "fine" };
  return {
    range: "7d",
    period: { start: "2026-03-09T00:00:00Z", end: "2026-03-15T12:00:00Z" },
    health: { status: "ok", database: up, redis: { ...up, latency_ms: 1 }, celery: up, workers: 3 },
    lessons: { started: 48, finished: 31, failed: 5, previous_started: 43, previous_finished: 33 },
    spend: { range_total: "3.840000", per_lesson_avg: "0.080000", month_to_date: "11.200000", monthly_budget: "25.000000" },
    calls: { total: 1476, ok: 1200, retried: 84, failed: 192, fallbacks: 61 },
    daily_spend: [],
    daily_activity: [],
    funnel: { started: 48, quick_check_done: 41, built: 33, test_submitted: 19, study_sheets: 6, failed_building: 5, waiting: 3 },
    slowest_steps: [],
    attention: [],
    ...patch,
  };
}

function usage(patch: Partial<ConsoleUsage> = {}): ConsoleUsage {
  return {
    range: "7d",
    period: { start: "2026-03-09T00:00:00Z", end: "2026-03-15T12:00:00Z" },
    kpis: { calls: 1476, tokens_in: 3_300_000, tokens_out: 800_000, spend: "3.840000", median_latency_s: 3.9, p95_latency_s: 41 },
    by_model: [
      { model: "openai/gpt-oss-120b", provider: "groq", median_s: 3.1, p95_s: 20, ok: 600, retried: 50, failed: 50, calls: 700, spend: "1.120000" },
      { model: "gemini-3.5-flash", provider: "gemini", median_s: 6, p95_s: 52.5, ok: 500, retried: 34, failed: 142, calls: 676, spend: "2.720000" },
      { model: "new-model", provider: "newco", median_s: null, p95_s: null, ok: 0, retried: 0, failed: 100, calls: 100, spend: "0.000000" },
    ],
    by_node: [
      { node: "page.generate", calls: 100, ok_pct: 90, retries: 5, fallbacks: 2, tokens_k: 900.5, spend: "2.000000", p95_s: 30 },
      { node: "lesson.plan", calls: 50, ok_pct: 100, retries: 0, fallbacks: 0, tokens_k: 100, spend: "0.500000", p95_s: 12 },
    ],
    ...patch,
  };
}

describe("ProviderSeries", () => {
  test.each([
    ["groq", "groq"],
    ["Groq", "groq"],
    ["gemini", "google"],
    ["google_genai", "google"],
    ["openai", "openai"],
    ["anthropic", "other"],
    ["", "other"],
  ])("%p is the %s series", (provider, series) => {
    expect(ProviderSeries.of(provider)).toBe(series as never);
  });

  test("colours are fixed per provider", () => {
    expect(ProviderSeries.color("groq")).toBe("var(--chart-cat-1)");
    expect(ProviderSeries.color("google")).toBe("var(--chart-cat-2)");
    expect(ProviderSeries.color("openai")).toBe("var(--chart-cat-3)");
    expect(ProviderSeries.color("other")).toBe("var(--chart-cat-other)");
    expect(ProviderSeries.label("openai")).toBe("OpenAI");
  });

  test("present series come in the fixed order, not the order found", () => {
    expect(ProviderSeries.present(["other", "google", "groq"])).toEqual(["groq", "google", "other"]);
  });
});

describe("SpendChart", () => {
  const daily: ConsoleOverview["daily_spend"] = [
    { date: "2026-03-14", by_provider: { gemini: "0.020000" } },
    { date: "2026-03-15", by_provider: { gemini: "0.010000", groq: "0.005000", anthropic: "0.001000", mistral: "0.002000" } },
    { date: "2026-03-16", by_provider: {} },
  ];

  test("makes a row a day, adding unknown providers into Other", () => {
    const data = SpendChart.shape(daily);

    expect(data.rows[1]).toMatchObject({ date: "2026-03-15", label: "15 Mar", google: 0.01, groq: 0.005, other: 0.003 });
    expect(data.rows[1]!.total).toBeCloseTo(0.018);
    expect(data.rows[2]!.total).toBe(0);
    expect(data.total).toBeCloseTo(0.038);
  });

  test("lists only the series that spent, in the fixed order", () => {
    expect(SpendChart.shape(daily).series).toEqual(["groq", "google", "other"]);
    expect(SpendChart.shape([{ date: "2026-03-15", by_provider: { openai: "0.1" } }]).series).toEqual(["openai"]);
    expect(SpendChart.shape([{ date: "2026-03-15", by_provider: {} }]).series).toEqual([]);
  });

  test("the top segment is the last series with spend that day", () => {
    const data = SpendChart.shape(daily);

    expect(SpendChart.topSeries(data.rows[0]!, data.series)).toBe("google");
    expect(SpendChart.topSeries(data.rows[1]!, data.series)).toBe("other");
    expect(SpendChart.topSeries(data.rows[2]!, data.series)).toBeNull();
  });

  test("has a table form", () => {
    const table = SpendChart.table(SpendChart.shape(daily));

    expect(table.headers).toEqual(["Day", "Groq", "Google", "Other", "Total"]);
    expect(table.rows[1]).toEqual(["Sun 15 Mar", "$0.0050", "$0.01", "$0.0030", "$0.02"]);
    expect(table.rows[2]).toEqual(["Mon 16 Mar", "$0.00", "$0.00", "$0.00", "$0.00"]);
  });
});

describe("Sparkline", () => {
  test("scales to the data: the highest value is at the top, the lowest at the bottom", () => {
    const { path, last } = Sparkline.shape([1, 3, 2]);

    expect(path).toBe("M3 31 L60 3 L117 17");
    expect(last).toEqual({ x: 117, y: 17 });
  });

  test("a gap breaks the line instead of drawing a zero", () => {
    expect(Sparkline.shape([1, null, 3]).path).toBe("M3 31 M117 3");
    expect(Sparkline.shape([null, 2, 3, null]).last).toMatchObject({ x: 79, y: 3 });
  });

  test("a constant series is a flat line in the middle, and nothing is nothing", () => {
    expect(Sparkline.shape([5, 5, 5]).path).toBe("M3 17 L60 17 L117 17");
    expect(Sparkline.shape([])).toEqual({ path: "", last: null });
    expect(Sparkline.shape([null, null])).toEqual({ path: "", last: null });
  });

  test("a single point is drawn at the left", () => {
    expect(Sparkline.shape([4])).toEqual({ path: "M3 17", last: { x: 3, y: 17 } });
  });
});

describe("OverviewKpis", () => {
  const activity = [
    { date: "2026-03-14", lessons_started: 3, calls_total: 100, calls_worked: 90 },
    { date: "2026-03-15", lessons_started: 5, calls_total: 0, calls_worked: 0 },
  ];
  const tiles = (patch: Partial<ConsoleOverview> = {}) => Object.fromEntries(OverviewKpis.of(overview({ daily_activity: activity, ...patch })).map((t) => [t.key, t]));

  test("there are four tiles, in order", () => {
    expect(OverviewKpis.of(overview()).map((t) => t.key)).toEqual(["started", "finished", "spend", "worked"]);
  });

  test("lessons started: the count, the change on the period before and the daily line", () => {
    const tile = tiles().started!;

    expect(tile).toMatchObject({ label: "Lessons started", value: "48", detail: "vs previous 7 days" });
    expect(tile.delta).toEqual({ label: "+12%", direction: "up", tone: "good" });
    expect(tile.spark!.values).toEqual([3, 5]);
  });

  test("fewer lessons than before is a bad change", () => {
    expect(tiles({ lessons: { ...overview().lessons, started: 20 } }).started!.delta).toMatchObject({ label: "−53%", tone: "bad" });
  });

  test("no lessons now or before has no change to show", () => {
    const tile = tiles({ lessons: { started: 0, finished: 0, failed: 0, previous_started: 0, previous_finished: 0 } }).started!;

    expect(tile.delta).toBeUndefined();
    expect(tile.value).toBe("0");
    expect(tile.detail).toContain("No lessons");
  });

  test("lessons finished: x of y, the change in points, a meter and the failures", () => {
    const tile = tiles().finished!;

    expect(tile).toMatchObject({ value: "31", suffix: "/ 48", detail: "65% made it to ready · 5 failed" });
    expect(tile.delta).toEqual({ label: "−12 pts", direction: "down", tone: "bad" }); // 64.6% against 76.7%
    expect(tile.meter).toMatchObject({ tone: "primary" });
    expect(tile.meter!.fraction).toBeCloseTo(0.646, 2);
  });

  test("finished with nothing started has no change, a full-width meter at most, and says so", () => {
    const tile = tiles({ lessons: { started: 0, finished: 2, failed: 0, previous_started: 0, previous_finished: 0 } }).finished!;

    expect(tile.delta).toBeUndefined();
    expect(tile.detail).toBe("Nothing started in this period");
    expect(tile.meter!.fraction).toBe(0);
  });

  test("more finished than started (they started earlier) never overfills the meter", () => {
    expect(tiles({ lessons: { started: 2, finished: 5, failed: 0, previous_started: 2, previous_finished: 2 } }).finished!.meter!.fraction).toBe(1);
  });

  test("a first period has no points change", () => {
    expect(tiles({ lessons: { started: 4, finished: 2, failed: 0, previous_started: 0, previous_finished: 0 } }).finished!.delta).toBeUndefined();
  });

  test("spend: the range, per lesson and the month against its budget", () => {
    const tile = tiles().spend!;

    expect(tile).toMatchObject({ value: "$3.84", detail: "$0.08 per lesson · month so far $11.20 of $25" });
    expect(tile.meter).toMatchObject({ tone: "primary", label: "Share of this month's budget spent" });
    expect(tile.meter!.fraction).toBeCloseTo(0.448);
  });

  test.each([
    ["19.9", "primary"],
    ["20", "marigold"],
    ["24.99", "marigold"],
    ["25", "destructive"],
    ["40", "destructive"],
  ])("a month of %s of $25 is the %s meter", (month, tone) => {
    const tile = tiles({ spend: { ...overview().spend, month_to_date: month } }).spend!;

    expect(tile.meter!.tone).toBe(tone as never);
    expect(tile.meter!.fraction).toBeLessThanOrEqual(1);
  });

  test("a budget of zero has an empty meter, not NaN", () => {
    expect(tiles({ spend: { ...overview().spend, monthly_budget: "0.000000" } }).spend!.meter!.fraction).toBe(0);
  });

  test("calls that worked: the share, the count, the fallbacks and a daily line with gaps", () => {
    const tile = tiles().worked!;

    expect(tile).toMatchObject({ value: "87%", detail: "1,284 of 1,476 · 61 fell back to another model" });
    expect(tile.spark!.values).toEqual([90, null]);
  });

  test("no calls is a dash and says so", () => {
    const tile = tiles({ calls: { total: 0, ok: 0, retried: 0, failed: 0, fallbacks: 0 } }).worked!;

    expect(tile.value).toBe("–");
    expect(tile.detail).toBe("No model calls in this period");
  });

  test("no fallbacks leaves that out", () => {
    expect(tiles({ calls: { total: 10, ok: 10, retried: 0, failed: 0, fallbacks: 0 } }).worked!.detail).toBe("10 of 10");
  });
});

describe("HealthPills", () => {
  test("shows each dependency with its time, and the workers", () => {
    expect(HealthPills.of(overview().health)).toEqual([
      { key: "database", label: "Database", detail: "4 ms", ok: true },
      { key: "redis", label: "Redis", detail: "1 ms", ok: true },
      { key: "workers", label: "Workers", detail: "3 running", ok: true },
    ]);
  });

  test("no worker, or a down dependency, is not ok", () => {
    const health = overview().health;
    const down = { ok: false, latency_ms: 0, detail: "refused" };

    expect(HealthPills.of({ ...health, workers: 0, celery: down })[2]).toMatchObject({ detail: "0 running", ok: false });
    expect(HealthPills.of({ ...health, redis: down })[1]!.ok).toBe(false);
    expect(HealthPills.of({ ...health, workers: 1 })[2]!.detail).toBe("1 running");
  });
});

describe("AttentionActions", () => {
  const item = (kind: never, severity: never, link = "/console/x") => ({ kind, severity, title: "t", detail: "d", link });

  test.each([
    ["lessons_failed", "error", "bad", "Review"],
    ["model_failing", "warning", "warn", "See calls"],
    ["rate_limit_waits", "info", "info", "Models"],
    ["provider_key_missing", "error", "bad", "Fix"],
  ])("%s as %s is %s with a %s button", (kind, severity, tone, label) => {
    expect(AttentionActions.of(item(kind as never, severity as never, "/console/where"))).toEqual({ tone: tone as never, actionLabel: label, href: "/console/where" });
  });
});

describe("FunnelChart", () => {
  const rows = FunnelChart.rows(overview().funnel);

  test("each step is a share of those started", () => {
    expect(rows.map((r) => [r.key, r.value, Math.round(r.share)])).toEqual([
      ["started", 48, 100],
      ["quick_check_done", 41, 85],
      ["built", 33, 69],
      ["test_submitted", 19, 40],
      ["study_sheets", 6, 13],
    ]);
  });

  test("says what became of the ones that did not get on", () => {
    expect(rows[1]!.note).toBe("7 have not answered it");
    expect(rows[2]!.note).toBe("5 failed while building · 3 waiting for the learner");
    expect(rows[0]!.note).toBeUndefined();
  });

  test("has no notes when everything got through, and no shares when nothing started", () => {
    const clean = FunnelChart.rows({ started: 4, quick_check_done: 4, built: 4, test_submitted: 4, study_sheets: 0, failed_building: 0, waiting: 0 });
    const empty = FunnelChart.rows({ started: 0, quick_check_done: 0, built: 0, test_submitted: 0, study_sheets: 0, failed_building: 0, waiting: 0 });

    expect(clean[1]!.note).toBeUndefined();
    expect(clean[2]!.note).toBeUndefined();
    expect(empty.every((r) => r.share === 0)).toBe(true);
  });
});

describe("SlowestSteps", () => {
  test("gives each step a readable time", () => {
    expect(SlowestSteps.rows([{ node: "page.generate", p95_s: 41.2 }, { node: "lesson.plan", p95_s: 0.8 }])).toEqual([
      { node: "page.generate", seconds: 41.2, label: "41 s" },
      { node: "lesson.plan", seconds: 0.8, label: "800 ms" },
    ]);
  });
});

describe("LatencyChart", () => {
  const rows = LatencyChart.rows(usage().by_model);

  test("draws the models that worked, with their provider's series", () => {
    expect(rows.map((r) => [r.model, r.series, r.median, r.p95])).toEqual([
      ["openai/gpt-oss-120b", "groq", 3.1, 20],
      ["gemini-3.5-flash", "google", 6, 52.5],
    ]);
  });

  test("the table keeps the models that never worked, with dashes", () => {
    const table = LatencyChart.table(usage().by_model);

    expect(table.headers).toEqual(["Model", "Provider", "Median", "p95"]);
    expect(table.rows[2]).toEqual(["new-model", "newco", "–", "–"]);
    expect(table.rows[1]).toEqual(["gemini-3.5-flash", "gemini", "6.0 s", "53 s"]);
  });

  test("the legend lists the providers that are there", () => {
    expect(LatencyChart.series(rows)).toEqual(["groq", "google"]);
  });
});

describe("OutcomeChart", () => {
  const rows = OutcomeChart.rows(usage().by_model);

  test("shares add up to 100 for a model with calls", () => {
    for (const row of rows.slice(0, 2)) expect(row.okShare + row.retriedShare + row.failedShare).toBeCloseTo(100);
    expect(rows[0]).toMatchObject({ total: 700, ok: 600 });
    expect(rows[0]!.okShare).toBeCloseTo(85.7, 1);
  });

  test("a model with no calls has no shares, not NaN", () => {
    const [row] = OutcomeChart.rows([{ model: "m", provider: "p", median_s: null, p95_s: null, ok: 0, retried: 0, failed: 0, calls: 0, spend: "0" }]);

    expect([row!.okShare, row!.retriedShare, row!.failedShare]).toEqual([0, 0, 0]);
  });

  test("has a table form with counts and shares", () => {
    const table = OutcomeChart.table(rows);

    expect(table.headers).toEqual(["Model", "Worked", "After retry", "Failed", "Calls"]);
    expect(table.rows[0]).toEqual(["openai/gpt-oss-120b", "600 (86%)", "50 (7%)", "50 (7%)", "700"]);
  });
});

describe("StepTable", () => {
  test("knows each step's spend as a number and against the costliest", () => {
    const rows = StepTable.rows(usage().by_node);

    expect(rows.map((r) => [r.node, r.spendValue, r.spendShare])).toEqual([
      ["page.generate", 2, 1],
      ["lesson.plan", 0.5, 0.25],
    ]);
  });

  test("steps that cost nothing have an empty bar", () => {
    expect(StepTable.rows([{ ...usage().by_node[0]!, spend: "0.000000" }])[0]!.spendShare).toBe(0);
    expect(StepTable.rows([])).toEqual([]);
  });
});

describe("UsageKpis", () => {
  test("four tiles with the share that worked, tokens, spend by provider and call times", () => {
    const tiles = UsageKpis.of(usage());

    expect(tiles.map((t) => [t.label, t.value])).toEqual([
      ["Calls", "1,476"],
      ["Tokens", "4.1M"],
      ["Spend", "$3.84"],
      ["Median call time", "3.9 s"],
    ]);
    expect(tiles[0]!.detail).toBe("80% worked first time or after a retry");
    expect(tiles[1]!.detail).toBe("3.3M in · 800k out");
    expect(tiles[2]!.detail).toBe("Groq $1.12 · Google $2.72");
    expect(tiles[3]!.detail).toBe("p95 41 s (includes rate-limit waits)");
  });

  test("nothing matching the filters says so", () => {
    const tiles = UsageKpis.of(usage({ kpis: { calls: 0, tokens_in: 0, tokens_out: 0, spend: "0.000000", median_latency_s: null, p95_latency_s: null }, by_model: [] }));

    expect(tiles[0]!.detail).toBe("No calls match these filters");
    expect(tiles[2]!.detail).toBe("No priced calls");
    expect(tiles[3]).toMatchObject({ value: "–", detail: "No call worked" });
  });
});

describe("RangeWords", () => {
  test("describes each range for a subtitle", () => {
    expect(RangeWords.of("today")).toBe("today");
    expect(RangeWords.of("7d")).toBe("last 7 days");
    expect(RangeWords.of("30d")).toBe("last 30 days");
  });

  test("a custom range names its first and last day", () => {
    expect(RangeWords.of("custom", { start: "2026-03-01T00:00:00Z", end: "2026-03-11T00:00:00Z" })).toBe("1 Mar to 10 Mar");
    expect(RangeWords.of("custom")).toBe("the chosen days");
  });
});

describe("hover tooltips and table forms", () => {
  test("a day's spend lists the providers that spent, then the total", () => {
    const data = SpendChart.shape([{ date: "2026-03-14", by_provider: { groq: "0.50", gemini: "1.25", mistral: "0" } }]);
    const tip = SpendChart.tooltip(data.rows[0]!, data.series);

    expect(tip.title).toBe(ConsoleFormat.dayLong(data.rows[0]!.date));
    expect(tip.rows.at(-1)).toEqual({ label: "Total", value: ConsoleFormat.money(data.rows[0]!.total) });
    expect(tip.rows.slice(0, -1).map((r) => r.label)).toEqual(data.series.filter((k) => (data.rows[0]![k] ?? 0) > 0).map(ProviderSeries.label));
    expect(tip.rows[0]!.color).toBe(ProviderSeries.color(data.series[0]!));
  });

  test("a funnel step says how many lessons and what share of those started", () => {
    const rows = FunnelChart.rows(overview().funnel);

    expect(FunnelChart.tooltip(rows[1]!)).toEqual({
      title: "Quick check done",
      rows: [
        { label: "Lessons", value: "41" },
        { label: "Of those started", value: "85%" },
      ],
    });
    expect(FunnelChart.table(rows).rows[1]).toEqual(["Quick check done", "41", "85%"]);
    expect(FunnelChart.table(rows).headers).toEqual(["Step", "Lessons", "Of those started"]);
  });

  test("a slow step says its p95, and has a table form", () => {
    const bars = SlowestSteps.rows([{ node: "page.generate", p95_s: 41.2 }]);

    expect(SlowestSteps.tooltip(bars[0]!)).toEqual({ title: "page.generate", rows: [{ label: "p95", value: "41 s" }] });
    expect(SlowestSteps.table(bars)).toEqual({ headers: ["Step", "p95"], rows: [["page.generate", "41 s"]] });
  });

  test("a model's call time shows median and p95 in its provider's colour", () => {
    const [row] = LatencyChart.rows(usage().by_model);

    expect(LatencyChart.tooltip(row!)).toEqual({
      title: "openai/gpt-oss-120b",
      rows: [
        { label: "Median", value: "3.1 s", color: ProviderSeries.color("groq") },
        { label: "p95", value: "20 s", color: ProviderSeries.color("groq") },
      ],
    });
  });

  test("the median bar is a share of the p95-long bar, and the tick sits at its end", () => {
    expect(LatencyChart.geometry(200, 5, 20)).toEqual({ barWidth: 50, tickX: 200 });
    expect(LatencyChart.geometry(200, 30, 20)).toEqual({ barWidth: 200, tickX: 200 });
    expect(LatencyChart.geometry(0, 0, 0)).toEqual({ barWidth: 0, tickX: 0 });
  });

  test("outcomes have fixed status colours, and the last segment with calls is the rounded one", () => {
    expect(OutcomeChart.SERIES.map((s) => [s.key, s.label, s.color])).toEqual([
      ["ok", "Worked", "var(--success)"],
      ["retried", "Worked after retry", "var(--marigold)"],
      ["failed", "Failed", "var(--destructive)"],
    ]);
    const [row] = OutcomeChart.rows(usage().by_model);
    expect(OutcomeChart.lastSegment(row!)).toBe("failed");
    expect(OutcomeChart.lastSegment({ ...row!, failed: 0 })).toBe("retried");
    expect(OutcomeChart.lastSegment({ ...row!, failed: 0, retried: 0 })).toBe("ok");
    expect(OutcomeChart.lastSegment({ ...row!, failed: 0, retried: 0, ok: 0 })).toBeNull();
  });

  test("a model's outcomes list counts with shares", () => {
    const [row] = OutcomeChart.rows(usage().by_model);

    expect(OutcomeChart.tooltip(row!)).toEqual({
      title: "openai/gpt-oss-120b",
      rows: [
        { label: "Worked", value: "600 (86%)", color: "var(--success)" },
        { label: "Worked after retry", value: "50 (7%)", color: "var(--marigold)" },
        { label: "Failed", value: "50 (7%)", color: "var(--destructive)" },
      ],
    });
  });
});

describe("provider colours and status colours never share a chart", () => {
  const componentColours = (file: string) =>
    [...readFileSync(join(import.meta.dir, "..", "components", "console", file), "utf8").matchAll(/var\((--[\w-]+)\)/g)].map((m) => ChartPalette.family(`var(${m[1]})`));

  test("the families are told apart", () => {
    expect(ChartPalette.family("var(--chart-cat-2)")).toBe("provider");
    expect(ChartPalette.family("var(--marigold)")).toBe("status");
    expect(ChartPalette.family("var(--foreground)")).toBe("neutral");
    expect(ChartPalette.family("#c27a0e")).toBe("unknown");
  });

  test("every provider has a provider colour", () => {
    for (const key of ["groq", "google", "openai", "other"] as const) expect(ChartPalette.family(ProviderSeries.color(key))).toBe("provider");
  });

  test("the outcome chart uses status colours only, in its data and in its tooltip", () => {
    const [row] = OutcomeChart.rows(usage().by_model);
    const tip = OutcomeChart.tooltip(row!);

    expect(OutcomeChart.SERIES.map((s) => ChartPalette.family(s.color))).toEqual(["status", "status", "status"]);
    expect(tip.rows.map((r) => ChartPalette.family(r.color!))).toEqual(["status", "status", "status"]);
  });

  test("the spend and call-time charts use provider colours only in their tooltips", () => {
    const spend = SpendChart.shape([{ date: "2026-03-14", by_provider: { groq: "0.50", gemini: "1.25", openai: "0.10", mistral: "0.2" } }]);
    const spendTip = SpendChart.tooltip(spend.rows[0]!, spend.series);
    const [model] = LatencyChart.rows(usage().by_model);

    const colours = [...spendTip.rows.filter((r) => r.label !== "Total"), ...LatencyChart.tooltip(model!).rows].map((r) => ChartPalette.family(r.color!));
    expect(new Set(colours)).toEqual(new Set(["provider"]));
  });

  test("the chart components draw with nothing from the other family", () => {
    expect(componentColours("usage/outcome-card.tsx")).not.toContain("provider");
    expect(componentColours("overview/spend-chart.tsx")).not.toContain("status");
    expect(componentColours("usage/latency-card.tsx")).not.toContain("status");
    for (const file of ["usage/outcome-card.tsx", "overview/spend-chart.tsx", "usage/latency-card.tsx"]) {
      expect(componentColours(file)).not.toContain("unknown");
    }
  });
});
