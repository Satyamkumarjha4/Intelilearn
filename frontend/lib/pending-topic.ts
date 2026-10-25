export type TopicStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const KEY = "socra.pendingTopic";

/**
 * The topic typed into the landing page before the visitor has an account, kept in `sessionStorage` through sign-up.
 * It is a convenience only: with no storage, broken storage or a blank box, nothing here ever throws.
 */
export class PendingTopic {
  constructor(
    private readonly storage: TopicStorage | undefined = PendingTopic.browserStorage(),
    private readonly maxLength = 200,
  ) {}

  save(raw: string): void {
    const topic = raw.trim().slice(0, this.maxLength).trim();
    this.guarded(() => (topic ? this.storage?.setItem(KEY, topic) : this.storage?.removeItem(KEY)));
  }

  /** The saved topic, left in place. */
  peek(): string | null {
    return this.guarded(() => this.storage?.getItem(KEY)) ?? null;
  }

  /** The saved topic, forgotten as it is read. */
  take(): string | null {
    const topic = this.peek();
    this.guarded(() => this.storage?.removeItem(KEY));
    return topic;
  }

  private guarded<T>(action: () => T): T | undefined {
    try {
      return action();
    } catch {
      return undefined;
    }
  }

  private static browserStorage(): TopicStorage | undefined {
    try {
      return typeof window === "undefined" ? undefined : window.sessionStorage;
    } catch {
      return undefined;
    }
  }
}
