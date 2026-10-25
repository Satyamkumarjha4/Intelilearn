import type { TestStatus } from "@/lib/types";

export type FlapTone = "primary" | "marigold" | "insight";
export type Flap = { index: number; label: string; tone: FlapTone; active: boolean; read: boolean };
export type NextAction = { kind: "page" | "test"; label: string };

const NAMES = ["Introduction", "Core", "Advanced"];
const TONES: FlapTone[] = ["primary", "marigold", "insight"];

/**
 * The state of the lesson notebook: which page is open out of how many, which pages were read, and what the labels,
 * flaps and the next button say. Immutable: every move returns a new book, so a render never sees it half-changed.
 * The document inside the iframe has no navigation of its own; the book tells it which page to show.
 */
export class LessonBook {
  constructor(
    readonly count: number,
    readonly titles: string[] = [],
    readonly index = 0,
    readonly read: ReadonlySet<number> = new Set(),
  ) {}

  get isFirst(): boolean {
    return this.index <= 0;
  }

  get isLast(): boolean {
    return this.index >= this.count - 1;
  }

  /** What the page is called on its flap: Introduction, Core, Advanced, else "Page n". */
  get name(): string {
    return this.nameOf(this.index);
  }

  /** The page's own title when the document sent it, else its name. */
  get title(): string {
    return this.titles[this.index] || this.name;
  }

  get eyebrow(): string {
    return this.count === 0 ? "Opening your lesson…" : `${this.footer} · ${this.name}`;
  }

  get footer(): string {
    return `Page ${this.index + 1} of ${this.count}`;
  }

  get flaps(): Flap[] {
    return Array.from({ length: this.count }, (_, index) => ({
      index,
      label: this.nameOf(index),
      tone: TONES[index % TONES.length],
      active: index === this.index,
      read: index !== this.index && this.read.has(index),
    }));
  }

  /** Open a page (never past either end). The page left behind counts as read. */
  goTo(index: number): LessonBook {
    const target = Math.min(Math.max(index, 0), Math.max(this.count - 1, 0));
    const read = new Set(this.read);
    if (target !== this.index) read.add(this.index);
    return new LessonBook(this.count, this.titles, target, read);
  }

  next(): LessonBook {
    return this.goTo(this.index + 1);
  }

  prev(): LessonBook {
    return this.goTo(this.index - 1);
  }

  /** The learner is done with this page (they pressed the last button), so it counts as read. */
  finish(): LessonBook {
    return new LessonBook(this.count, this.titles, this.index, new Set(this.read).add(this.index));
  }

  /** The pages read in an earlier visit (kept in this browser) join the ones read now. */
  withRead(read: ReadonlySet<number>): LessonBook {
    return new LessonBook(this.count, this.titles, this.index, new Set([...this.read, ...[...read].filter((page) => page < this.count || this.count === 0)]));
  }

  /** The document told us its pages: keep the place and the ticks that still make sense. */
  withPages(count: number, titles: string[]): LessonBook {
    const read = new Set([...this.read].filter((page) => page < count));
    return new LessonBook(count, titles, Math.min(this.index, Math.max(count - 1, 0)), read);
  }

  /** The button on the right of the footer: the next page, or on the last page the way to the test. */
  nextAction(test: TestStatus): NextAction {
    if (!this.isLast) return { kind: "page", label: "Next page →" };
    return { kind: "test", label: test === "not_started" ? "Go to the test →" : "See your test results →" };
  }

  private nameOf(index: number): string {
    return this.count === NAMES.length ? NAMES[index] : `Page ${index + 1}`;
  }
}

type Storage = Pick<globalThis.Storage, "getItem" | "setItem">;

/** The pages of a lesson the learner has read, kept in this browser. It works without storage: no ticks, no crash. */
export class ReadPages {
  constructor(
    private readonly lessonId: string,
    private readonly storage: Storage | null = ReadPages.browserStorage(),
  ) {}

  load(): Set<number> {
    try {
      const parsed: unknown = JSON.parse(this.storage?.getItem(this.key) ?? "[]");
      if (!Array.isArray(parsed)) return new Set();
      return new Set(parsed.filter((n): n is number => Number.isInteger(n) && n >= 0));
    } catch {
      return new Set();
    }
  }

  save(read: ReadonlySet<number>): void {
    try {
      this.storage?.setItem(this.key, JSON.stringify([...read].sort((a, b) => a - b)));
    } catch {
      // Storage is full or blocked: the ticks just last until the page is closed.
    }
  }

  private get key(): string {
    return `lesson-book:read:${this.lessonId}`;
  }

  private static browserStorage(): Storage | null {
    try {
      return typeof window === "undefined" ? null : window.localStorage;
    } catch {
      return null; // reading `localStorage` itself can throw when site data is blocked
    }
  }
}

type KeyEvent = {
  key: string;
  altKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  target: {
    tagName?: string;
    isContentEditable?: boolean;
    getAttribute?: (name: string) => string | null;
    closest?: (selector: string) => unknown;
  } | null;
};

/** Which way an arrow key turns the page (−1 back, 1 forward, 0 not at all). */
export class BookKeys {
  private static readonly TYPING = new Set(["INPUT", "TEXTAREA", "SELECT"]);

  static direction(event: KeyEvent): -1 | 0 | 1 {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return 0;
    const target = event.target;
    if (target && (BookKeys.TYPING.has(target.tagName ?? "") || target.isContentEditable || target.getAttribute?.("role") === "slider")) return 0;
    if (target?.closest?.('[role="dialog"], [role="menu"]')) return 0; // a dialog or menu has its own arrow keys
    return event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
  }
}
