import { CreditsApi, creditsApi } from "./credits-api";
import type { CostAsk } from "./cost-sizes";
import type { Quote } from "./types";

type Quoter = Pick<CreditsApi, "quote" | "retryQuote">;

/**
 * Asks the server what something costs, and remembers the answer for a short while so a form that changes a choice and
 * changes it back does not ask twice, and two labels with the same question share one request. A price it cannot get
 * (the network, a missing price) is `null`: a label that cannot say the price says nothing, and never blocks the action.
 */
export class QuoteClient {
  static readonly TTL_MS = 30_000;
  private readonly cache = new Map<string, { at: number; quote: Quote }>();
  private readonly asking = new Map<string, Promise<Quote | null>>();

  constructor(
    private readonly api: Quoter = creditsApi,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /** A question's identity: the action and its hints, whatever order the hints were written in. */
  static key(ask: CostAsk): string {
    const hints = Object.entries(ask.size).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `${ask.action}|${JSON.stringify(hints)}`;
  }

  /** The answer if it is fresh, without asking. */
  cached(ask: CostAsk): Quote | undefined {
    return this.fresh(QuoteClient.key(ask));
  }

  async quote(ask: CostAsk): Promise<Quote | null> {
    const key = QuoteClient.key(ask);
    const known = this.fresh(key);
    if (known) return known;
    return this.ask(key, () => this.api.quote(ask.action, ask.size));
  }

  /** What Retry on a failed lesson would ask for now (nothing when the work was kept). */
  retry(lessonId: string): Promise<Quote | null> {
    const key = `retry|${lessonId}`;
    const known = this.fresh(key);
    return known ? Promise.resolve(known) : this.ask(key, () => this.api.retryQuote(lessonId));
  }

  /** Forget everything: after a price may have changed, or the learner's wallet was topped up. */
  clear(): void {
    this.cache.clear();
  }

  private fresh(key: string): Quote | undefined {
    const hit = this.cache.get(key);
    if (hit && this.now() - hit.at < QuoteClient.TTL_MS) return hit.quote;
    this.cache.delete(key);
    return undefined;
  }

  private ask(key: string, send: () => Promise<Quote>): Promise<Quote | null> {
    const pending = this.asking.get(key);
    if (pending) return pending;
    const request = send()
      .then((quote) => {
        this.cache.set(key, { at: this.now(), quote });
        return quote;
      })
      .catch(() => null)
      .finally(() => this.asking.delete(key));
    this.asking.set(key, request);
    return request;
  }
}

export const quoteClient = new QuoteClient();
