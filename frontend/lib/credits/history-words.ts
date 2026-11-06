import { ShortDate } from "./short-date";
import type { Transaction } from "./types";

export type HistoryDay = { key: string; heading: string; rows: Transaction[] };

/** The history list in a learner's words: grouped by day, and the change drawn with its sign. */
export class HistoryWords {
  /** "+10", "−3", "0". The minus is a real minus sign, which reads better and is not mistaken for a hyphen. */
  static amount(amount: number): string {
    if (amount > 0) return `+${amount}`;
    if (amount < 0) return `−${Math.abs(amount)}`;
    return "0";
  }

  static tone(amount: number): "gain" | "spend" | "none" {
    return amount > 0 ? "gain" : amount < 0 ? "spend" : "none";
  }

  /** Rows are newest first already; a day's rows stay together in that order. */
  static byDay(rows: Transaction[], now: Date = new Date()): HistoryDay[] {
    const days: HistoryDay[] = [];
    for (const row of rows) {
      const at = new Date(row.created_at);
      const key = `${at.getFullYear()}-${at.getMonth()}-${at.getDate()}`;
      const last = days[days.length - 1];
      if (last && last.key === key) last.rows.push(row);
      else days.push({ key, heading: HistoryWords.heading(at, now), rows: [row] });
    }
    return days;
  }

  static heading(at: Date, now: Date): string {
    const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const diff = Math.round((day(now) - day(at)) / 86_400_000);
    if (diff === 0) return "Today";
    if (diff === 1) return "Yesterday";
    return ShortDate.of(at);
  }

  static time(at: string): string {
    return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" }).format(new Date(at));
  }

  static readonly EMPTY = "Nothing here yet. When you earn or use credits, you'll see it here.";
}
