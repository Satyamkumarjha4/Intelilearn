/**
 * "Fri 14 Nov", the same in every browser. `Intl` puts a comma after the weekday in some locales and not in others, so the
 * parts are put together here.
 */
export class ShortDate {
  private static readonly format = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });

  static of(at: Date): string {
    const part = (type: string) => ShortDate.format.formatToParts(at).find((p) => p.type === type)?.value ?? "";
    return `${part("weekday")} ${part("day")} ${part("month")}`;
  }
}
