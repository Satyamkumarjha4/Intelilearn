import type { CallOutcome, ConsoleRange, UsageFilters, UsageRange } from "@/lib/types";

/** What the console reads from the address bar: `URLSearchParams` and Next's `useSearchParams()` both fit. */
export type Params = { get(name: string): string | null };

const RANGES: readonly ConsoleRange[] = ["today", "7d", "30d"];
const OUTCOMES: readonly CallOutcome[] = ["ok", "retried", "failed"];
const DEFAULT_RANGE: ConsoleRange = "7d";
const MAX_CUSTOM_DAYS = 366;
const DAY_MS = 86_400_000;

/**
 * The console's page state lives in the address, so a view can be shared, bookmarked and survives a reload: the
 * overview's `?range=`, and the usage page's `?range=&start=&end=&provider=&model=&node=&outcome=`. Reading is forgiving
 * (anything unusable falls back to the default, so a hand-edited link never breaks the page) and writing leaves out
 * what is already the default.
 */
export class ConsoleUrl {
  static overviewRange(params: Params): ConsoleRange {
    const range = params.get("range");
    return RANGES.includes(range as ConsoleRange) ? (range as ConsoleRange) : DEFAULT_RANGE;
  }

  /** `""` for the default range, else `?range=30d`. */
  static overviewQuery(range: ConsoleRange): string {
    return range === DEFAULT_RANGE ? "" : `?range=${range}`;
  }

  static usageFilters(params: Params): UsageFilters {
    const text = (name: string) => params.get(name)?.trim() ?? "";
    const outcome = text("outcome") as CallOutcome;
    const filters: UsageFilters = {
      range: DEFAULT_RANGE,
      provider: text("provider"),
      model: text("model"),
      node: text("node"),
      outcome: OUTCOMES.includes(outcome) ? outcome : "",
    };
    const range = text("range");
    if (RANGES.includes(range as ConsoleRange)) filters.range = range as ConsoleRange;
    if (range === "custom" && ConsoleUrl.validDays(text("start"), text("end"))) {
      Object.assign(filters, { range: "custom", start: text("start"), end: text("end") });
    }
    return filters;
  }

  /** `""` when every filter is the default, else `?range=30d&provider=groq`. */
  static usageQuery(filters: UsageFilters): string {
    const range = filters.range ?? DEFAULT_RANGE;
    const pairs: [string, string | undefined][] = [
      ["range", range === DEFAULT_RANGE ? undefined : range],
      ["start", range === "custom" ? filters.start : undefined],
      ["end", range === "custom" ? filters.end : undefined],
      ["provider", filters.provider],
      ["model", filters.model],
      ["node", filters.node],
      ["outcome", filters.outcome],
    ];
    const search = new URLSearchParams();
    for (const [name, value] of pairs) if (value) search.set(name, value);
    const text = search.toString();
    return text ? `?${text}` : "";
  }

  /** The filters with another range: a custom one starts as the last 7 days up to `today`, the others drop the dates. */
  static withRange(filters: UsageFilters, range: UsageRange, today: Date = new Date()): UsageFilters {
    if (range !== "custom") return { ...filters, range, start: undefined, end: undefined };
    const end = ConsoleUrl.isoDay(today);
    return { ...filters, range, start: filters.start || ConsoleUrl.isoDay(new Date(today.getTime() - 6 * DAY_MS)), end: filters.end || end };
  }

  /** A date as the API takes it: `YYYY-MM-DD`, the UTC day. */
  static isoDay(date: Date): string {
    return date.toISOString().slice(0, 10);
  }

  /** True for two real dates, in order, at most a year apart (what the API accepts for a custom range). */
  static validDays(start: string, end: string): boolean {
    const first = ConsoleUrl.parseDay(start);
    const last = ConsoleUrl.parseDay(end);
    if (first === null || last === null) return false;
    const days = Math.round((last - first) / DAY_MS) + 1;
    return days >= 1 && days <= MAX_CUSTOM_DAYS;
  }

  private static parseDay(value: string): number | null {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const time = Date.parse(`${value}T00:00:00Z`);
    return Number.isNaN(time) || new Date(time).toISOString().slice(0, 10) !== value ? null : time;
  }
}
