import type { ConsoleRange, Money, UsageRange } from "@/lib/types";

export type Delta = { label: string; direction: "up" | "down" | "flat" };

const MINUS = "−";
const NUMBERS = new Intl.NumberFormat("en-US");

/**
 * How the console writes numbers: US dollars, call times, counts and changes. One place, so a figure reads the same on
 * every page. The console is English-only, so the locale is fixed (and the output the same on every machine).
 */
export class ConsoleFormat {
  /** "1,476". */
  static count(value: number): string {
    return NUMBERS.format(Math.round(value));
  }

  /** "950", "3.3k", "4.1M": for tokens, where the exact figure is noise. */
  static compact(value: number): string {
    const size = Math.abs(value);
    if (size >= 1_000_000 || Number((size / 1_000).toFixed(1)) >= 1_000) return `${ConsoleFormat.trim(value / 1_000_000, 1)}M`;
    if (size >= 1_000) return `${ConsoleFormat.trim(value / 1_000, 1)}k`;
    return ConsoleFormat.count(value);
  }

  /** US dollars: "$3.84", "$1,234", four places below a cent ("$0.0042") so a cheap call is not "$0.00", and "<$0.0001" below that. */
  static money(value: Money | number | null | undefined): string {
    const amount = Number(value);
    if (value === null || value === undefined || value === "" || Number.isNaN(amount)) return "–";
    const sign = amount < 0 ? MINUS : "";
    const size = Math.abs(amount);
    if (size === 0) return "$0.00";
    if (size < 0.0001) return `${sign === "" ? "<" : sign}$0.0001`;
    if (size < 0.01) return `${sign}$${size.toFixed(4)}`;
    if (size >= 1000) return `${sign}$${NUMBERS.format(Math.round(size))}`;
    return `${sign}$${size.toFixed(2)}`;
  }

  /** `money` without ".00" on a whole number of dollars ("$25"), for a budget or a limit. */
  static moneyShort(value: Money | number | null | undefined): string {
    return ConsoleFormat.money(value).replace(/\.00$/, "");
  }

  /** A chart axis label for dollars: "$0", "$0.5", "$12". */
  static moneyAxis(value: number): string {
    return `$${ConsoleFormat.trim(value, 2)}`;
  }

  /** A call time: "420 ms", "3.9 s", "41 s", "2 min 5 s", "1 h 5 min". */
  static duration(seconds: number | null | undefined): string {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
    if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
    if (seconds < 10) return `${seconds.toFixed(1)} s`;
    const total = Math.round(seconds);
    if (total < 60) return `${total} s`;
    if (total < 3600) {
      const rest = total % 60;
      return rest ? `${Math.floor(total / 60)} min ${rest} s` : `${total / 60} min`;
    }
    const minutes = Math.floor((total % 3600) / 60);
    return minutes ? `${Math.floor(total / 3600)} h ${minutes} min` : `${total / 3600} h`;
  }

  /** A chart axis label for seconds: "0", "5 s", "2.5 s", "1.5 min". */
  static durationAxis(seconds: number): string {
    if (seconds === 0) return "0";
    return seconds < 60 ? `${ConsoleFormat.trim(seconds, 1)} s` : `${ConsoleFormat.trim(seconds / 60, 1)} min`;
  }

  /** "87%" (a figure that is already 0 to 100). */
  static percent(value: number, digits = 0): string {
    return `${ConsoleFormat.trim(value, digits)}%`;
  }

  /** `part` as a percentage of `whole` (0 when there is no whole). */
  static ratio(part: number, whole: number): number {
    return whole > 0 ? (100 * part) / whole : 0;
  }

  /** The change from `previous` to `current` as a percentage: "+12%", "−5%", "new" from nothing, null when both are 0. */
  static percentDelta(current: number, previous: number): Delta | null {
    if (previous === 0) return current === 0 ? null : { label: "new", direction: "up" };
    const change = Math.round((100 * (current - previous)) / previous);
    return ConsoleFormat.delta(change, "%");
  }

  /** The change in a percentage, in points: "+3 pts", "−5 pts". Null when there is nothing to compare with. */
  static pointsDelta(current: number | null, previous: number | null): Delta | null {
    if (current === null || previous === null) return null;
    return ConsoleFormat.delta(Math.round(current - previous), " pts");
  }

  /** The words for what a delta compares with: "vs previous 7 days". */
  static versus(range: ConsoleRange): string {
    return range === "today" ? "vs yesterday" : `vs previous ${range === "7d" ? "7" : "30"} days`;
  }

  /** "Today", "7 days", "30 days", "Custom". */
  static rangeLabel(range: UsageRange): string {
    return { today: "Today", "7d": "7 days", "30d": "30 days", custom: "Custom" }[range];
  }

  /** "15 Mar" from a YYYY-MM-DD date or an ISO time (days are UTC days, as the API counts them). */
  static day(iso: string): string {
    return ConsoleFormat.dateParts(iso, { day: "numeric", month: "short" });
  }

  /** "Sun 15 Mar". */
  static dayLong(iso: string): string {
    return ConsoleFormat.dateParts(iso, { weekday: "short", day: "numeric", month: "short" }).replace(",", "");
  }

  private static dateParts(iso: string, options: Intl.DateTimeFormatOptions): string {
    const date = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("en-GB", { ...options, timeZone: "UTC" });
  }

  private static delta(change: number, unit: string): Delta {
    if (change === 0) return { label: `0${unit}`, direction: "flat" };
    const sign = change > 0 ? "+" : MINUS;
    return { label: `${sign}${Math.abs(change)}${unit}`, direction: change > 0 ? "up" : "down" };
  }

  /** `value` to at most `digits` decimals, without trailing zeros. */
  private static trim(value: number, digits: number): string {
    return String(Number(value.toFixed(digits)));
  }
}
