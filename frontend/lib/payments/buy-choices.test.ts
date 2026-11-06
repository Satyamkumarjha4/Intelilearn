/**
 * Unit under test: `OneTimeChoices` and `PlanQuantity`, what a learner picks to buy and what it comes to.
 *
 * Why: the one-time amount is a few chips and a box, bounded by the server's smallest and largest; a plan by the week is a
 * small stepper bounded by the most that can be bought at once. The totals shown are only what to expect (the server prices
 * the order again), but they must be right, and a chip must never be an amount that would be refused.
 *
 * Use cases:
 * - the preset chips are 50, 100, 200 and 500, less any the server's limits would refuse
 * - a chip gives its credits and rupees; the box is checked against the limits and says why when it is not allowed; an empty
 *   box with no chip is nothing yet; a chip wins over the box
 * - the total reads as rupees for credits
 * - a plan's quantity is held between 1 and what the plan allows, a plan bought whole has no choice, and the total follows
 */
import { describe, expect, test } from "bun:test";

import type { OneTimeRules, Plan } from "@/lib/credits/types";

import { OneTimeChoices, PlanQuantity } from "./buy-choices";

const rules: OneTimeRules = { min_credits: 10, max_credits: 5000, price_paise_per_credit: 100, valid_days: 365 };
const weekly: Plan = { key: "weekly_pro", name: "Weekly Pro", kind: "recurring", credits: 100, period_days: 7, price_paise: 4900, max_quantity: 12 };
const monthly: Plan = { ...weekly, key: "monthly_pro", name: "Monthly Pro", credits: 500, period_days: 28, price_paise: 19900, max_quantity: 1 };

describe("the amount of one-time credits", () => {
  test("the chips are the presets the limits allow", () => {
    expect(OneTimeChoices.presets(rules)).toEqual([50, 100, 200, 500]);
    expect(OneTimeChoices.presets({ ...rules, min_credits: 100, max_credits: 300 })).toEqual([100, 200]);
  });

  test("a chip gives its credits and its price", () => {
    expect(OneTimeChoices.amount(200, "", rules)).toEqual({ credits: 200, paise: 20000 });
  });

  test("the box is checked against the limits and says why not", () => {
    expect(OneTimeChoices.amount(null, "250", rules)).toEqual({ credits: 250, paise: 25000 });
    expect(OneTimeChoices.amount(null, "5", rules)).toEqual({ message: "The smallest amount is 10 credits." });
    expect(OneTimeChoices.amount(null, "abc", rules)).toEqual({ message: "Enter a whole number of credits." });
  });

  test("nothing picked and nothing typed is nothing yet; a chip wins over the box", () => {
    expect(OneTimeChoices.amount(null, "  ", rules)).toBeNull();
    expect(OneTimeChoices.amount(50, "999", rules)).toEqual({ credits: 50, paise: 5000 });
  });

  test("the total reads as rupees for credits", () => {
    expect(OneTimeChoices.total(250, rules)).toBe("₹250 for 250 credits");
  });
});

describe("a plan's quantity", () => {
  test("is held between one and what the plan allows", () => {
    expect([0, -3, 1, 7, 12, 99, Number.NaN].map((n) => PlanQuantity.clamp(weekly, n))).toEqual([1, 1, 1, 7, 12, 12, 1]);
  });

  test("a plan bought whole has no choice and always one", () => {
    expect(PlanQuantity.canChoose(monthly)).toBe(false);
    expect(PlanQuantity.canChoose(weekly)).toBe(true);
    expect(PlanQuantity.clamp(monthly, 5)).toBe(1);
  });

  test("the total follows the weeks", () => {
    expect(PlanQuantity.total(weekly, 3)).toEqual({ paise: 14700, credits: 300 });
    expect(PlanQuantity.total(weekly, 50)).toEqual({ paise: 58800, credits: 1200 });
  });

  test("the weeks read in words, and a plan bought whole says nothing", () => {
    expect(PlanQuantity.words(weekly, 1)).toBe("1 week");
    expect(PlanQuantity.words(weekly, 4)).toBe("4 weeks");
    expect(PlanQuantity.words(monthly, 1)).toBe("");
  });
});
