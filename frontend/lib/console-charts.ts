import { ConsoleFormat } from "@/lib/console-format";
import type { Attention, ConsoleOverview, ConsoleRange, ConsoleUsage } from "@/lib/types";

/** What a chart's hover box shows: a title, then a row per series or measure. */
export type TooltipData = { title: string; rows: { label: string; value: string; color?: string }[] };

// --- providers: a fixed colour each, never by rank ------------------------------------------------------------------

export type SeriesKey = "groq" | "google" | "openai" | "other";

/** The categorical series of the charts. A provider always has the same colour (Groq, Google, OpenAI; any other is the
 *  grey "Other"), whatever it spent, so a colour means the same thing on every chart and every day. */
/**
 * Which family a chart colour belongs to. A chart is coloured by provider (categorical) or by status (worked, retried,
 * failed), never both: a reader who has learned that amber means "Google" must not meet amber meaning "retried".
 */
export class ChartPalette {
  static readonly PROVIDER = ["--chart-cat-1", "--chart-cat-2", "--chart-cat-3", "--chart-cat-other"] as const;
  static readonly STATUS = ["--success", "--marigold", "--destructive"] as const;
  /** Chrome, not data: the cursor, the p95 tick. Allowed in any chart. */
  static readonly NEUTRAL = ["--foreground", "--muted", "--border", "--muted-foreground"] as const;

  static family(color: string): "provider" | "status" | "neutral" | "unknown" {
    const token = /^var\((--[\w-]+)\)$/.exec(color)?.[1] ?? "";
    if ((ChartPalette.PROVIDER as readonly string[]).includes(token)) return "provider";
    if ((ChartPalette.STATUS as readonly string[]).includes(token)) return "status";
    if ((ChartPalette.NEUTRAL as readonly string[]).includes(token)) return "neutral";
    return "unknown";
  }
}

export class ProviderSeries {
  static readonly ORDER: readonly SeriesKey[] = ["groq", "google", "openai", "other"];
  private static readonly LABELS: Record<SeriesKey, string> = { groq: "Groq", google: "Google", openai: "OpenAI", other: "Other" };
  private static readonly COLORS: Record<SeriesKey, string> = {
    groq: "var(--chart-cat-1)",
    google: "var(--chart-cat-2)",
    openai: "var(--chart-cat-3)",
    other: "var(--chart-cat-other)",
  };

  /** The series of a provider key from the registry ("gemini" is Google's). */
  static of(providerKey: string): SeriesKey {
    const key = providerKey.trim().toLowerCase();
    if (key === "groq") return "groq";
    if (["google", "gemini", "google_genai", "vertex"].includes(key)) return "google";
    if (key === "openai") return "openai";
    return "other";
  }

  static label(key: SeriesKey): string {
    return ProviderSeries.LABELS[key];
  }

  static color(key: SeriesKey): string {
    return ProviderSeries.COLORS[key];
  }

  /** The series that occur in `keys`, in the fixed order. */
  static present(keys: Iterable<SeriesKey>): SeriesKey[] {
    const found = new Set(keys);
    return ProviderSeries.ORDER.filter((key) => found.has(key));
  }
}

// --- daily spend ---------------------------------------------------------------------------------------------------

export type SpendRow = { date: string; label: string; total: number } & Partial<Record<SeriesKey, number>>;
export type SpendChartData = { rows: SpendRow[]; series: SeriesKey[]; total: number };

/** The daily spend as stacked bars: a row per day with a number per provider series (other providers add up into
 *  "Other"), and the series that have any spend. */
export class SpendChart {
  static shape(daily: ConsoleOverview["daily_spend"]): SpendChartData {
    const rows: SpendRow[] = daily.map((day) => {
      const row: SpendRow = { date: day.date, label: ConsoleFormat.day(day.date), total: 0 };
      for (const [provider, amount] of Object.entries(day.by_provider)) {
        const key = ProviderSeries.of(provider);
        row[key] = (row[key] ?? 0) + Number(amount);
        row.total += Number(amount);
      }
      return row;
    });
    const series = ProviderSeries.present(ProviderSeries.ORDER.filter((key) => rows.some((row) => (row[key] ?? 0) > 0)));
    return { rows, series, total: rows.reduce((sum, row) => sum + row.total, 0) };
  }

  /** The top segment of a day's bar (the last series, in order, that spent anything): the only one with rounded corners. */
  static topSeries(row: SpendRow, series: readonly SeriesKey[]): SeriesKey | null {
    return [...series].reverse().find((key) => (row[key] ?? 0) > 0) ?? null;
  }

  /** A day's hover box: what each provider that spent cost, then the total. */
  static tooltip(row: SpendRow, series: readonly SeriesKey[]): TooltipData {
    return {
      title: ConsoleFormat.dayLong(row.date),
      rows: [
        ...series.filter((key) => (row[key] ?? 0) > 0).map((key) => ({ label: ProviderSeries.label(key), value: ConsoleFormat.money(row[key]), color: ProviderSeries.color(key) })),
        { label: "Total", value: ConsoleFormat.money(row.total) },
      ],
    };
  }

  /** The chart as a table: one column per series and a total. */
  static table(data: SpendChartData): { headers: string[]; rows: string[][] } {
    return {
      headers: ["Day", ...data.series.map(ProviderSeries.label), "Total"],
      rows: data.rows.map((row) => [
        ConsoleFormat.dayLong(row.date),
        ...data.series.map((key) => ConsoleFormat.money(row[key] ?? 0)),
        ConsoleFormat.money(row.total),
      ]),
    };
  }
}

// --- sparklines ----------------------------------------------------------------------------------------------------

export type SparkShape = { path: string; last: { x: number; y: number } | null };

/** A line through a series, for a tile. A gap (null) breaks the line instead of drawing a false zero. */
export class Sparkline {
  static readonly WIDTH = 120;
  static readonly HEIGHT = 34;
  private static readonly PAD = 3;

  static shape(values: readonly (number | null)[]): SparkShape {
    const known = values.filter((value): value is number => value !== null);
    if (!known.length) return { path: "", last: null };
    const low = Math.min(...known);
    const high = Math.max(...known);
    const usable = Sparkline.HEIGHT - 2 * Sparkline.PAD;
    const step = values.length > 1 ? (Sparkline.WIDTH - 2 * Sparkline.PAD) / (values.length - 1) : 0;
    const point = (value: number, index: number) => ({
      x: Sparkline.round(Sparkline.PAD + index * step),
      y: Sparkline.round(high === low ? Sparkline.HEIGHT / 2 : Sparkline.PAD + usable * (1 - (value - low) / (high - low))),
    });

    let path = "";
    let last: { x: number; y: number } | null = null;
    let drawing = false;
    values.forEach((value, index) => {
      if (value === null) {
        drawing = false;
        return;
      }
      last = point(value, index);
      path += `${drawing ? " L" : path ? " M" : "M"}${last.x} ${last.y}`;
      drawing = true;
    });
    return { path, last };
  }

  private static round(value: number): number {
    return Math.round(value * 10) / 10;
  }
}

// --- the four tiles of the overview ----------------------------------------------------------------------------------

export type MeterTone = "primary" | "marigold" | "destructive";
export type DeltaTone = "good" | "bad" | "neutral";
export type KpiData = {
  key: string;
  label: string;
  value: string;
  /** Smaller text after the value ("/ 48"). */
  suffix?: string;
  detail: string;
  delta?: { label: string; direction: "up" | "down" | "flat"; tone: DeltaTone };
  /** 0 to 1. */
  meter?: { fraction: number; tone: MeterTone; label: string };
  spark?: { values: (number | null)[]; label: string };
};

/** What each overview tile shows, worked out from the overview reply. */
export class OverviewKpis {
  static of(overview: ConsoleOverview): KpiData[] {
    return [
      OverviewKpis.started(overview),
      OverviewKpis.finished(overview),
      OverviewKpis.spend(overview),
      OverviewKpis.worked(overview),
    ];
  }

  private static started({ lessons, range, daily_activity }: ConsoleOverview): KpiData {
    const change = ConsoleFormat.percentDelta(lessons.started, lessons.previous_started);
    return {
      key: "started",
      label: "Lessons started",
      value: ConsoleFormat.count(lessons.started),
      detail: change ? ConsoleFormat.versus(range) : "No lessons in this period or the one before",
      delta: change ? { ...change, tone: change.direction === "down" ? "bad" : change.direction === "up" ? "good" : "neutral" } : undefined,
      spark: { values: daily_activity.map((day) => day.lessons_started), label: "Lessons started each day" },
    };
  }

  private static finished({ lessons }: ConsoleOverview): KpiData {
    const share = ConsoleFormat.ratio(lessons.finished, lessons.started);
    const before = lessons.previous_started > 0 ? ConsoleFormat.ratio(lessons.previous_finished, lessons.previous_started) : null;
    const change = lessons.started > 0 ? ConsoleFormat.pointsDelta(share, before) : null;
    const failed = lessons.failed > 0 ? ` · ${ConsoleFormat.count(lessons.failed)} failed` : "";
    return {
      key: "finished",
      label: "Lessons finished",
      value: ConsoleFormat.count(lessons.finished),
      suffix: `/ ${ConsoleFormat.count(lessons.started)}`,
      detail: lessons.started > 0 ? `${ConsoleFormat.percent(share)} made it to ready${failed}` : `Nothing started in this period${failed}`,
      delta: change ? { ...change, tone: change.direction === "down" ? "bad" : change.direction === "up" ? "good" : "neutral" } : undefined,
      meter: { fraction: Math.min(1, share / 100), tone: "primary", label: "Share of started lessons that are ready" },
    };
  }

  private static spend({ spend }: ConsoleOverview): KpiData {
    const budget = Number(spend.monthly_budget);
    const used = budget > 0 ? Number(spend.month_to_date) / budget : 0;
    return {
      key: "spend",
      label: "AI spend",
      value: ConsoleFormat.money(spend.range_total),
      detail: `${ConsoleFormat.money(spend.per_lesson_avg)} per lesson · month so far ${ConsoleFormat.money(spend.month_to_date)} of ${ConsoleFormat.moneyShort(spend.monthly_budget)}`,
      meter: { fraction: Math.min(1, used), tone: used >= 1 ? "destructive" : used >= 0.8 ? "marigold" : "primary", label: "Share of this month's budget spent" },
    };
  }

  private static worked({ calls, daily_activity }: ConsoleOverview): KpiData {
    const worked = calls.ok + calls.retried;
    const fellBack = calls.fallbacks > 0 ? ` · ${ConsoleFormat.count(calls.fallbacks)} fell back to another model` : "";
    return {
      key: "worked",
      label: "Model calls that worked",
      value: calls.total > 0 ? ConsoleFormat.percent(ConsoleFormat.ratio(worked, calls.total)) : "–",
      detail: calls.total > 0 ? `${ConsoleFormat.count(worked)} of ${ConsoleFormat.count(calls.total)}${fellBack}` : "No model calls in this period",
      spark: {
        values: daily_activity.map((day) => (day.calls_total > 0 ? ConsoleFormat.ratio(day.calls_worked, day.calls_total) : null)),
        label: "Share of calls that worked each day",
      },
    };
  }
}

// --- health, attention, funnel, slowest steps -----------------------------------------------------------------------

export type HealthPillData = { key: string; label: string; detail: string; ok: boolean };

export class HealthPills {
  static of(health: ConsoleOverview["health"]): HealthPillData[] {
    return [
      { key: "database", label: "Database", detail: `${health.database.latency_ms} ms`, ok: health.database.ok },
      { key: "redis", label: "Redis", detail: `${health.redis.latency_ms} ms`, ok: health.redis.ok },
      {
        key: "workers",
        label: "Workers",
        detail: health.workers === 1 ? "1 running" : `${health.workers} running`,
        ok: health.celery.ok && health.workers > 0,
      },
    ];
  }
}

export type AttentionTone = "bad" | "warn" | "info";
export type AttentionView = { tone: AttentionTone; actionLabel: string; href: string };

/** How an attention item is drawn and where its button goes (the API gives the page; the label says what is there). */
export class AttentionActions {
  private static readonly LABELS: Record<Attention["kind"], string> = {
    lessons_failed: "Review",
    model_failing: "See calls",
    rate_limit_waits: "Models",
    provider_key_missing: "Fix",
  };

  static of(item: Attention): AttentionView {
    const tone = { error: "bad", warning: "warn", info: "info" } as const;
    return { tone: tone[item.severity], actionLabel: AttentionActions.LABELS[item.kind] ?? "Open", href: item.link };
  }
}

export type FunnelRow = { key: string; label: string; value: number; share: number; note?: string };

/** Where the lessons of the range stop: each step as a share of the lessons started, with what happened to the rest. */
export class FunnelChart {
  static rows(funnel: ConsoleOverview["funnel"]): FunnelRow[] {
    const row = (key: string, label: string, value: number, note?: string): FunnelRow => ({
      key,
      label,
      value,
      share: ConsoleFormat.ratio(value, funnel.started),
      note: note || undefined,
    });
    const unanswered = funnel.started - funnel.quick_check_done;
    const stuck = [
      funnel.failed_building > 0 ? `${ConsoleFormat.count(funnel.failed_building)} failed while building` : "",
      funnel.waiting > 0 ? `${ConsoleFormat.count(funnel.waiting)} waiting for the learner` : "",
    ];
    return [
      row("started", "Started", funnel.started),
      row("quick_check_done", "Quick check done", funnel.quick_check_done, unanswered > 0 ? `${ConsoleFormat.count(unanswered)} have not answered it` : ""),
      row("built", "Lesson built", funnel.built, stuck.filter(Boolean).join(" · ")),
      row("test_submitted", "Test submitted", funnel.test_submitted),
      row("study_sheets", "Study sheets", funnel.study_sheets, "Learners who answered the whole quick check right"),
    ];
  }

  static tooltip(row: FunnelRow): TooltipData {
    return {
      title: row.label,
      rows: [
        { label: "Lessons", value: ConsoleFormat.count(row.value) },
        { label: "Of those started", value: ConsoleFormat.percent(row.share) },
      ],
    };
  }

  static table(rows: readonly FunnelRow[]): { headers: string[]; rows: string[][] } {
    return {
      headers: ["Step", "Lessons", "Of those started"],
      rows: rows.map((row) => [row.label, ConsoleFormat.count(row.value), ConsoleFormat.percent(row.share)]),
    };
  }
}

export type StepBar = { node: string; seconds: number; label: string };

export class SlowestSteps {
  static rows(steps: ConsoleOverview["slowest_steps"]): StepBar[] {
    return steps.map((step) => ({ node: step.node, seconds: step.p95_s, label: ConsoleFormat.duration(step.p95_s) }));
  }

  static tooltip(bar: StepBar): TooltipData {
    return { title: bar.node, rows: [{ label: "p95", value: bar.label }] };
  }

  static table(bars: readonly StepBar[]): { headers: string[]; rows: string[][] } {
    return { headers: ["Step", "p95"], rows: bars.map((bar) => [bar.node, bar.label]) };
  }
}

// --- usage -----------------------------------------------------------------------------------------------------------

export type LatencyRow = { id: string; model: string; provider: string; series: SeriesKey; median: number; p95: number };

/** Call time per model: the median as a bar and the p95 as a tick; models that never worked have no time to draw. */
export class LatencyChart {
  static rows(byModel: ConsoleUsage["by_model"]): LatencyRow[] {
    return byModel.flatMap((row) =>
      row.median_s === null || row.p95_s === null
        ? []
        : [{ id: `${row.provider}/${row.model}`, model: row.model, provider: row.provider, series: ProviderSeries.of(row.provider), median: row.median_s, p95: row.p95_s }],
    );
  }

  static table(byModel: ConsoleUsage["by_model"]): { headers: string[]; rows: string[][] } {
    return {
      headers: ["Model", "Provider", "Median", "p95"],
      rows: byModel.map((row) => [row.model, row.provider, ConsoleFormat.duration(row.median_s), ConsoleFormat.duration(row.p95_s)]),
    };
  }

  static tooltip(row: LatencyRow): TooltipData {
    const color = ProviderSeries.color(row.series);
    return {
      title: row.model,
      rows: [
        { label: "Median", value: ConsoleFormat.duration(row.median), color },
        { label: "p95", value: ConsoleFormat.duration(row.p95), color },
      ],
    };
  }

  /** The bar is as long as the p95 (`width` is that length); the median fills its share of it and the tick sits at the end. A
   *  median above the p95 (they come from different calls' interpolation) is capped so it never passes the tick. */
  static geometry(width: number, median: number, p95: number): { barWidth: number; tickX: number } {
    if (!(width > 0) || !(p95 > 0)) return { barWidth: 0, tickX: 0 };
    return { barWidth: width * Math.min(1, median / p95), tickX: width };
  }

  /** The series present among the models, for the legend. */
  static series(rows: readonly LatencyRow[]): SeriesKey[] {
    return ProviderSeries.present(rows.map((row) => row.series));
  }
}

export type OutcomeKey = "ok" | "retried" | "failed";

export type OutcomeRow = {
  id: string;
  model: string;
  provider: string;
  ok: number;
  retried: number;
  failed: number;
  total: number;
  okShare: number;
  retriedShare: number;
  failedShare: number;
};

/** Calls per model by what came of them: worked first time, worked after a retry, failed (each a share of the model's calls). */
export class OutcomeChart {
  /** Worked, worked after a retry, failed: the status colours (never used for anything else), always in this order. */
  static readonly SERIES: readonly { key: OutcomeKey; label: string; color: string }[] = [
    { key: "ok", label: "Worked", color: "var(--success)" },
    { key: "retried", label: "Worked after retry", color: "var(--marigold)" },
    { key: "failed", label: "Failed", color: "var(--destructive)" },
  ];

  /** The outermost segment of a model's bar (the only one with a rounded end). */
  static lastSegment(row: Pick<OutcomeRow, OutcomeKey>): OutcomeKey | null {
    return [...OutcomeChart.SERIES].reverse().find((series) => row[series.key] > 0)?.key ?? null;
  }

  static tooltip(row: OutcomeRow): TooltipData {
    const shares = { ok: row.okShare, retried: row.retriedShare, failed: row.failedShare };
    return {
      title: row.model,
      rows: OutcomeChart.SERIES.map(({ key, label, color }) => ({
        label,
        value: `${ConsoleFormat.count(row[key])} (${ConsoleFormat.percent(shares[key])})`,
        color,
      })),
    };
  }

  static rows(byModel: ConsoleUsage["by_model"]): OutcomeRow[] {
    return byModel.map((row) => {
      const total = row.ok + row.retried + row.failed;
      return {
        id: `${row.provider}/${row.model}`,
        model: row.model,
        provider: row.provider,
        ok: row.ok,
        retried: row.retried,
        failed: row.failed,
        total,
        okShare: ConsoleFormat.ratio(row.ok, total),
        retriedShare: ConsoleFormat.ratio(row.retried, total),
        failedShare: ConsoleFormat.ratio(row.failed, total),
      };
    });
  }

  static table(rows: readonly OutcomeRow[]): { headers: string[]; rows: string[][] } {
    return {
      headers: ["Model", "Worked", "After retry", "Failed", "Calls"],
      rows: rows.map((row) => [
        row.model,
        `${ConsoleFormat.count(row.ok)} (${ConsoleFormat.percent(row.okShare)})`,
        `${ConsoleFormat.count(row.retried)} (${ConsoleFormat.percent(row.retriedShare)})`,
        `${ConsoleFormat.count(row.failed)} (${ConsoleFormat.percent(row.failedShare)})`,
        ConsoleFormat.count(row.total),
      ]),
    };
  }
}

export type StepRow = ConsoleUsage["by_node"][number] & { spendValue: number; spendShare: number };

/** The "by lesson step" table: the API's rows with the spend as a number and as a share of the costliest step (for the bar). */
export class StepTable {
  static rows(byNode: ConsoleUsage["by_node"]): StepRow[] {
    const top = Math.max(0, ...byNode.map((row) => Number(row.spend)));
    return byNode.map((row) => ({ ...row, spendValue: Number(row.spend), spendShare: top > 0 ? Number(row.spend) / top : 0 }));
  }
}

/** The KPI tiles of the usage page. */
export class UsageKpis {
  static of(usage: ConsoleUsage): { key: string; label: string; value: string; detail: string }[] {
    const { kpis, by_model } = usage;
    const worked = by_model.reduce((sum, row) => sum + row.ok + row.retried, 0);
    const bySeries = new Map<SeriesKey, number>();
    for (const row of by_model) bySeries.set(ProviderSeries.of(row.provider), (bySeries.get(ProviderSeries.of(row.provider)) ?? 0) + Number(row.spend));
    const split = ProviderSeries.ORDER.filter((key) => (bySeries.get(key) ?? 0) > 0).map((key) => `${ProviderSeries.label(key)} ${ConsoleFormat.money(bySeries.get(key))}`);
    return [
      {
        key: "calls",
        label: "Calls",
        value: ConsoleFormat.count(kpis.calls),
        detail: kpis.calls > 0 ? `${ConsoleFormat.percent(ConsoleFormat.ratio(worked, kpis.calls))} worked first time or after a retry` : "No calls match these filters",
      },
      {
        key: "tokens",
        label: "Tokens",
        value: ConsoleFormat.compact(kpis.tokens_in + kpis.tokens_out),
        detail: `${ConsoleFormat.compact(kpis.tokens_in)} in · ${ConsoleFormat.compact(kpis.tokens_out)} out`,
      },
      { key: "spend", label: "Spend", value: ConsoleFormat.money(kpis.spend), detail: split.length ? split.join(" · ") : "No priced calls" },
      {
        key: "median",
        label: "Median call time",
        value: ConsoleFormat.duration(kpis.median_latency_s),
        detail: kpis.p95_latency_s === null ? "No call worked" : `p95 ${ConsoleFormat.duration(kpis.p95_latency_s)} (includes rate-limit waits)`,
      },
    ];
  }
}

/** The title words of a range, for card subtitles: "last 7 days". */
export class RangeWords {
  static of(range: ConsoleRange | "custom", period?: { start: string; end: string }): string {
    if (range === "custom") return period ? `${ConsoleFormat.day(period.start)} to ${ConsoleFormat.day(new Date(Date.parse(period.end) - 1).toISOString())}` : "the chosen days";
    return { today: "today", "7d": "last 7 days", "30d": "last 30 days" }[range];
  }
}
