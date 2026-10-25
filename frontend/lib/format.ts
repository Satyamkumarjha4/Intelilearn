/** Dates as a learner reads them. */
export class DateText {
  /** "24 Oct 2026" (in the reader's own language and order). */
  static day(iso: string, locale?: string): string {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(locale, { dateStyle: "medium", timeZone: "UTC" });
  }
}
