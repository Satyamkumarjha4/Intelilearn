/**
 * Everything the sign-up form and the profile page know about a time zone (docs/archive/credits-implementation-plan.md,
 * D9). The learner's day, for the daily credit and the streak, is the day in their zone: sign-up sends the browser's,
 * and the profile lets them correct it once every 30 days. The server decides all of it; this saves a refused request.
 */
export class BrowserTimezone {
  /** The zone a learner with none saved is on, as the server has it. */
  static readonly DEFAULT = "Asia/Kolkata";
  static readonly LOCK_DAYS = 30;
  static readonly RULE = `You can change this once every ${BrowserTimezone.LOCK_DAYS} days.`;

  /** The browser's zone, or null when the engine can't say. */
  static detect(resolve: () => string | undefined = () => Intl.DateTimeFormat().resolvedOptions().timeZone): string | null {
    try {
      return resolve()?.trim() || null;
    } catch {
      return null;
    }
  }

  /** What the profile shows first: the saved zone, else the browser's, else India's. */
  static initial(saved: string, detected: string | null): string {
    return saved || detected || BrowserTimezone.DEFAULT;
  }

  /** The zones to offer: the engine's list plus the saved and detected ones, sorted, each once. */
  static names(list: (() => string[]) | null = BrowserTimezone.engineList, saved = "", detected: string | null = null): string[] {
    let supported: string[] = [];
    try {
      supported = list?.() ?? [];
    } catch {
      supported = [];
    }
    const known = new Set([...supported, saved, detected ?? "", ...(supported.length ? [] : [BrowserTimezone.DEFAULT])].filter(Boolean));
    return [...known].sort();
  }

  /** Names matching the words typed: case, spaces, slashes, dashes and underscores don't matter; a word that starts with the search ranks first. */
  static search(names: string[], query: string): string[] {
    const wanted = BrowserTimezone.compact(query);
    if (!wanted) return names;
    const starts: string[] = [];
    const contains: string[] = [];
    for (const name of names) {
      if (!BrowserTimezone.compact(name).includes(wanted)) continue;
      const words = name.toLowerCase().split(/[/_\-\s]+/);
      const startsAWord = words.some((_, index) => BrowserTimezone.compact(words.slice(index).join("")).startsWith(wanted));
      (startsAWord ? starts : contains).push(name);
    }
    return [...starts, ...contains];
  }

  static isValid(name: string, names: string[]): boolean {
    return names.includes(name);
  }

  /** Whether the server will refuse a change now. An unreadable date never locks anybody out. */
  static isLocked(lockedUntil: string | null, now: Date): boolean {
    const until = BrowserTimezone.parse(lockedUntil);
    return until !== null && until.getTime() > now.getTime();
  }

  /** "You can change your time zone again on 5 December 2026." (the date in the learner's zone), or null when open. */
  static lockNote(lockedUntil: string | null, now: Date, zone: string): string | null {
    const until = BrowserTimezone.parse(lockedUntil);
    return until !== null && BrowserTimezone.isLocked(lockedUntil, now) ? BrowserTimezone.lockedSentence(until, zone) : null;
  }

  /** The words for the server's `409 timezone_locked`, which carries `locked_until`. */
  static lockedMessage(lockedUntil: unknown, zone: string): string {
    const until = typeof lockedUntil === "string" ? BrowserTimezone.parse(lockedUntil) : null;
    return until ? BrowserTimezone.lockedSentence(until, zone) : "You changed your time zone recently. Try again in a few weeks.";
  }

  /** The zone to send with a save: only when it changed, or when none was saved yet. */
  static payload(chosen: string, saved: string): { timezone?: string } {
    const name = chosen.trim();
    return name && name !== saved ? { timezone: name } : {};
  }

  private static engineList(): string[] {
    return (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  }

  private static compact(text: string): string {
    return text.toLowerCase().replace(/[^a-z0-9]/g, "");
  }

  private static parse(value: string | null): Date | null {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  private static lockedSentence(until: Date, zone: string): string {
    const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: zone }).format(until);
    return `You can change your time zone again on ${day}.`;
  }
}
