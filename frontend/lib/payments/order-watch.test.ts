/**
 * Unit under test: `OrderWatch`, what the page a learner comes back to after paying does while it waits.
 *
 * Why: it must never decide anything from its own address, only from what the server says about the order; it should be quick
 * while a webhook is likely to land and gentler after, say plainly when it is taking long without alarming anyone, and stop
 * once the server has settled the matter, one way or the other.
 *
 * Use cases:
 * - fulfilled is done, failed and expired are failed, and neither is asked about again
 * - a waiting order is asked about every 2 seconds for the first 30, then every 6
 * - after two minutes, or when the last ask failed, the words become "still confirming" and it carries on asking
 * - after twenty minutes it stops asking and says so (the job that settles it carries on without the page)
 * - before the first answer it is waiting
 */
import { describe, expect, test } from "bun:test";

import { OrderWatch } from "./order-watch";
import type { Order, OrderStatus } from "./types";

const order = (status: OrderStatus): Order => ({
  id: "o1", status, gateway: "fake", plan: { key: "one_time", name: "One-time credits" }, quantity: 1, credits: 100,
  amount_paise: 10000, currency: "INR", refunded_paise: 0, created_at: "2026-11-07T10:00:00Z", fulfilled_at: null,
});

describe("settled", () => {
  test("fulfilled is done and not asked about again", () => {
    expect(OrderWatch.next(order("fulfilled"), 5000)).toEqual({ phase: "done", pollIn: null });
  });

  test.each(["failed", "expired"] as const)("%s is failed and not asked about again", (status) => {
    expect(OrderWatch.next(order(status), 5000)).toEqual({ phase: "failed", pollIn: null });
  });

  test("a settled order stays settled however long it took", () => {
    expect(OrderWatch.next(order("fulfilled"), 60 * 60_000).phase).toBe("done");
  });
});

describe("waiting", () => {
  test("is quick at first and gentler after half a minute", () => {
    expect(OrderWatch.next(order("pending"), 0)).toEqual({ phase: "waiting", pollIn: 2000 });
    expect(OrderWatch.next(order("paid"), 29_999).pollIn).toBe(2000);
    expect(OrderWatch.next(order("pending"), 30_000).pollIn).toBe(6000);
  });

  test("before the first answer it is waiting", () => {
    expect(OrderWatch.next(null, 0)).toEqual({ phase: "waiting", pollIn: 2000 });
  });

  test("after two minutes, or after a failed ask, it says it is still confirming and carries on", () => {
    expect(OrderWatch.next(order("pending"), 120_000)).toEqual({ phase: "slow", pollIn: 6000 });
    expect(OrderWatch.next(order("pending"), 1000, true)).toEqual({ phase: "slow", pollIn: 2000 });
  });

  test("after twenty minutes it stops asking and says it is still confirming", () => {
    expect(OrderWatch.next(order("pending"), 20 * 60_000)).toEqual({ phase: "slow", pollIn: null });
  });
});
