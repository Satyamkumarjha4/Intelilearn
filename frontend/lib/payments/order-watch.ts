import type { Order } from "./types";

export type Phase = "waiting" | "slow" | "done" | "failed";

export type Step = { phase: Phase; /** Milliseconds until the next ask, or null when there is nothing more to wait for. */ pollIn: number | null };

/**
 * What the return page does while a payment is being confirmed. It decides nothing from its own address: it asks the server
 * for the order and goes by the answer. Quick polls at first (a webhook usually lands in seconds), slower later, a calm
 * "still confirming" after a few minutes, and it stops for good once the server says fulfilled, failed or expired. Pure.
 */
export class OrderWatch {
  static readonly QUICK_MS = 2000;
  static readonly SLOW_MS = 6000;
  static readonly FAST_FOR_MS = 30_000;
  static readonly CALM_AFTER_MS = 120_000;
  static readonly GIVE_UP_AFTER_MS = 20 * 60_000;

  /** `order` is null before the first answer; `error` is true when the last ask failed (try again; it may be the network). */
  static next(order: Order | null, elapsedMs: number, error = false): Step {
    if (order?.status === "fulfilled") return { phase: "done", pollIn: null };
    if (order?.status === "failed" || order?.status === "expired") return { phase: "failed", pollIn: null };
    if (elapsedMs >= OrderWatch.GIVE_UP_AFTER_MS) return { phase: "slow", pollIn: null };
    const pollIn = elapsedMs < OrderWatch.FAST_FOR_MS ? OrderWatch.QUICK_MS : OrderWatch.SLOW_MS;
    return { phase: elapsedMs >= OrderWatch.CALM_AFTER_MS || error ? "slow" : "waiting", pollIn };
  }
}
