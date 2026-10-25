/** "I don't know" is an answer, the useful one when unsure. */
export const DONT_KNOW = "dont_know" as const;

/** An option's index, the learner's own words, or "I don't know". */
export type DeckAnswer = number | string;
export type Segment = "done" | "current" | "todo";
export type DeckSnapshot = { index: number; answers: Record<string, DeckAnswer>; finished: boolean };

/**
 * A learner working through a deck of cards (the quick check and the final test): one card at a time, forward only.
 * The answer on the current card can change until they continue; continuing needs an answer, locks the card, and there
 * is no way back. Continuing on the last card finishes the deck. Answers stay here until the end, when all go to the
 * server in one request.
 */
export class DeckSession {
  private readonly answers = new Map<string, DeckAnswer>();
  private position = 0;
  private done: boolean;

  constructor(readonly ids: string[]) {
    this.done = ids.length === 0;
  }

  get index(): number {
    return this.position;
  }

  get total(): number {
    return this.ids.length;
  }

  get current(): string | undefined {
    return this.done ? undefined : this.ids[this.position];
  }

  get isLast(): boolean {
    return !this.done && this.position === this.ids.length - 1;
  }

  get finished(): boolean {
    return this.done;
  }

  get answeredCount(): number {
    return this.answers.size;
  }

  get canContinue(): boolean {
    return this.current !== undefined && this.answers.has(this.current);
  }

  get segments(): Segment[] {
    return this.ids.map((_, i): Segment => (this.done || i < this.position ? "done" : i === this.position ? "current" : "todo"));
  }

  answerOf(id: string): DeckAnswer | undefined {
    return this.answers.get(id);
  }

  /** A card the learner has continued past: its answer can no longer change. */
  isLocked(id: string): boolean {
    return this.done || this.ids.indexOf(id) < this.position;
  }

  /** Answer the current card. `null`, or text that is blank, takes the answer away (the card is unanswered again). */
  answer(value: DeckAnswer | null): void {
    const id = this.current;
    if (id === undefined) return;
    if (value === null || (typeof value === "string" && value.trim() === "")) {
      this.answers.delete(id);
      return;
    }
    if (typeof value === "number" ? !Number.isInteger(value) || value < 0 : typeof value !== "string") {
      throw new RangeError(`${String(value)} is not an answer`);
    }
    this.answers.set(id, value);
  }

  /** Lock the current card and move on (on the last card: finish). False when it has no answer yet. */
  continue(): boolean {
    if (!this.canContinue) return false;
    if (this.isLast) this.done = true;
    else this.position += 1;
    return true;
  }

  /** Every answer, once the deck is finished. */
  payload(): Record<string, DeckAnswer> {
    if (!this.done || this.answers.size !== this.ids.length) throw new Error("Answer every question before submitting");
    return Object.fromEntries(this.answers);
  }

  snapshot(): DeckSnapshot {
    return { index: this.position, answers: Object.fromEntries(this.answers), finished: this.done };
  }

  /** Picks up where a snapshot left off. What does not fit the deck is mended, not trusted: unknown cards and odd
   *  answers are dropped, and the place cannot be past a card that has no answer. */
  static restore(ids: string[], snapshot: DeckSnapshot): DeckSession {
    const deck = new DeckSession(ids);
    for (const id of ids) {
      const value = snapshot.answers[id];
      if (value === undefined) continue;
      try {
        deck.position = deck.ids.indexOf(id);
        deck.answer(value);
      } catch {
        // an answer of the wrong kind is dropped
      }
    }
    const wanted = Math.min(Math.max(Math.trunc(snapshot.index) || 0, 0), ids.length);
    let place = 0;
    while (place < wanted && place < ids.length && deck.answers.has(ids[place])) place += 1;
    deck.position = Math.min(place, Math.max(ids.length - 1, 0));
    deck.done = ids.length === 0 || (snapshot.finished === true && ids.every((id) => deck.answers.has(id)));
    return deck;
  }
}

type Storage = Pick<globalThis.Storage, "getItem" | "setItem" | "removeItem">;

/** Keeps a deck in `sessionStorage`, so a refresh resumes on the same card with earlier answers still locked. It works
 *  without storage (a refresh just starts over). */
export class DeckStore {
  constructor(
    private readonly key: string,
    private readonly storage: Storage | null = DeckStore.browserStorage(),
  ) {}

  load(ids: string[]): DeckSession | null {
    try {
      const raw: unknown = JSON.parse(this.storage?.getItem(`deck:${this.key}`) ?? "null");
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
      const { index, answers, finished } = raw as Record<string, unknown>;
      if (typeof index !== "number" || !answers || typeof answers !== "object" || Array.isArray(answers)) return null;
      return DeckSession.restore(ids, { index, answers: answers as Record<string, DeckAnswer>, finished: finished === true });
    } catch {
      return null;
    }
  }

  save(deck: DeckSession): void {
    try {
      this.storage?.setItem(`deck:${this.key}`, JSON.stringify(deck.snapshot()));
    } catch {
      // full or blocked: a refresh starts over
    }
  }

  clear(): void {
    try {
      this.storage?.removeItem(`deck:${this.key}`);
    } catch {
      // nothing to forget
    }
  }

  private static browserStorage(): Storage | null {
    try {
      return typeof window === "undefined" ? null : window.sessionStorage;
    } catch {
      return null;
    }
  }
}
