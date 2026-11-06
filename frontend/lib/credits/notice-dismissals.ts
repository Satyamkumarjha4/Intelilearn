import type { Notice } from "./types";

type Store = Pick<Storage, "getItem" | "setItem">;

/**
 * "Not now" for a notice about credits running out: hidden for the rest of the day, in this browser (credits plan T27).
 * The next day it shows again, because the credits are still about to run out. Nothing is stored on the server, and a
 * browser that will not store (private mode) simply forgets when the page is reloaded.
 */
export class NoticeDismissals {
  static readonly KEY = "socra.notices.dismissed";
  private memory: { day: string; ids: string[] } | null = null;

  constructor(
    private readonly store: Store | null = typeof window === "undefined" ? null : window.localStorage,
    private readonly today: () => string = NoticeDismissals.localDay,
  ) {}

  /** The browser's own date as `YYYY-MM-DD`. */
  static localDay(): string {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  }

  isDismissed(id: string): boolean {
    return this.read().ids.includes(id);
  }

  dismiss(id: string): void {
    const kept = this.read();
    if (kept.ids.includes(id)) return;
    this.write({ day: kept.day, ids: [...kept.ids, id] });
  }

  /** Only the notices not put away today. */
  visible(notices: Notice[]): Notice[] {
    const kept = this.read();
    return notices.filter((notice) => !kept.ids.includes(notice.id));
  }

  private read(): { day: string; ids: string[] } {
    const today = this.today();
    const stored = this.fromStore() ?? this.memory;
    return stored && stored.day === today ? stored : { day: today, ids: [] };
  }

  private fromStore(): { day: string; ids: string[] } | null {
    try {
      const parsed: unknown = JSON.parse(this.store?.getItem(NoticeDismissals.KEY) ?? "null");
      if (!parsed || typeof parsed !== "object") return null;
      const { day, ids } = parsed as { day?: unknown; ids?: unknown };
      return typeof day === "string" && Array.isArray(ids) ? { day, ids: ids.filter((id): id is string => typeof id === "string") } : null;
    } catch {
      return null;
    }
  }

  private write(value: { day: string; ids: string[] }): void {
    this.memory = value;
    try {
      this.store?.setItem(NoticeDismissals.KEY, JSON.stringify(value));
    } catch {
      // storage is full or refused: the in-memory copy still hides it for this visit
    }
  }
}
