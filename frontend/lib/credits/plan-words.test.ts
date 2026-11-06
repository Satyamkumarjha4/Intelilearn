/**
 * Unit under test: `PlanWords` and `BuyState`, the buy page's words and the one-time amount's checks.
 *
 * Why: money is paise on the wire and rupees on screen, so the formatting must be exact; the amount of one-time credits
 * has a smallest and a largest that come from the server, and a number typed in a box must be checked against them before
 * anything is shown as a price. (The server checks again and computes the amount; this only spares a round trip.)
 *
 * Use cases:
 * - paise become rupees, with paise only when there are some
 * - a plan reads as its price and what it gives, for a week and for other lengths; one-time credits read as a price a credit
 * - a running period reads as running until, a waiting one as starting
 * - the amount: whole numbers within the server's limits give credits and paise; text, fractions, zero and out-of-range do not
 * - buying is closed in this phase and says so in the product's words
 */
import { describe, expect, test } from "bun:test";

import { BuyState, PlanWords } from "./plan-words";
import type { OneTimeRules, Plan, PlanPeriod, Plans } from "./types";

const weekly: Plan = { key: "weekly_pro", name: "Weekly Pro", kind: "recurring", credits: 100, period_days: 7, price_paise: 4900, max_quantity: 12 };
const monthly: Plan = { key: "monthly_pro", name: "Monthly Pro", kind: "recurring", credits: 500, period_days: 28, price_paise: 19900, max_quantity: 1 };
const oneTime: Plan = { key: "one_time", name: "Credits", kind: "one_time", credits: 0, period_days: 365, price_paise: 100, max_quantity: 1 };
const rules: OneTimeRules = { min_credits: 10, max_credits: 5000, price_paise_per_credit: 100, valid_days: 365 };

describe("money", () => {
  test("paise become rupees, with paise only when there are some", () => {
    expect(PlanWords.rupees(4900)).toBe("₹49");
    expect(PlanWords.rupees(4950)).toBe("₹49.50");
    expect(PlanWords.rupees(100000)).toBe("₹1,000");
    expect(PlanWords.rupees(0)).toBe("₹0");
  });
});

describe("plans", () => {
  test("read as a price and what they give", () => {
    expect(PlanWords.price(weekly)).toBe("₹49 a week");
    expect(PlanWords.price(monthly)).toBe("₹199 for 28 days");
    expect(PlanWords.price(oneTime)).toBe("₹1 a credit");
    expect(PlanWords.gives(weekly)).toBe("100 credits every week");
    expect(PlanWords.gives(monthly)).toBe("500 credits every 28 days");
  });

  test("only the recurring ones are the plans", () => {
    const plans = { plans: [oneTime, weekly, monthly], one_time: rules, periods: [], queue: { open: 0, limit: 12 } } satisfies Plans;

    expect(PlanWords.recurring(plans).map((p) => p.key)).toEqual(["weekly_pro", "monthly_pro"]);
  });

  test("a running period reads as running until, a waiting one as starting", () => {
    const base: PlanPeriod = { plan: "weekly_pro", plan_name: "Weekly Pro", status: "active", starts_at: new Date(2026, 10, 5).toISOString(), ends_at: new Date(2026, 10, 12).toISOString(), credits: 100 };

    expect(PlanWords.period(base)).toBe("Weekly Pro: 100 credits, running until Thu 12 Nov");
    expect(PlanWords.period({ ...base, status: "queued" })).toBe("Weekly Pro: 100 credits, starts Thu 5 Nov");
    expect(PlanWords.queue({ open: 2, limit: 12 })).toBe("2 of 12 plan periods lined up");
  });

  test("how long bought credits last", () => {
    expect(PlanWords.valid(365)).toBe("a year");
    expect(PlanWords.valid(90)).toBe("90 days");
  });
});

describe("the one-time amount", () => {
  test("a whole number within the limits gives credits and paise", () => {
    expect(PlanWords.check("250", rules)).toEqual({ ok: true, credits: 250, paise: 25000 });
    expect(PlanWords.check(" 10 ", rules)).toMatchObject({ ok: true, credits: 10 });
    expect(PlanWords.check("5000", rules)).toMatchObject({ ok: true });
  });

  test.each(["", "abc", "12.5", "-20", "1e3", "0x10"])("%p is not a whole number", (text) => {
    expect(PlanWords.check(text, rules)).toEqual({ ok: false, message: "Enter a whole number of credits." });
  });

  test("below the smallest and above the largest say the limit", () => {
    expect(PlanWords.check("9", rules)).toEqual({ ok: false, message: "The smallest amount is 10 credits." });
    expect(PlanWords.check("5001", rules)).toEqual({ ok: false, message: "The most you can buy at once is 5000 credits." });
  });
});

test("buying is closed in this phase, and says so", () => {
  expect(BuyState.OPEN).toBe(false);
  expect(BuyState.CLOSED_TEXT).toBe("Buying isn't open yet");
});
