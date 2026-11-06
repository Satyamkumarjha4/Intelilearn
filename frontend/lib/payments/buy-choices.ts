import type { OneTimeRules, Plan } from "@/lib/credits/types";

import { PlanWords } from "@/lib/credits/plan-words";

/** What to buy, as the buy page lets a learner choose it, and what it comes to. The server prices every order again from its
 *  own table; the totals here only show a learner what to expect. */
export class OneTimeChoices {
  static readonly PRESETS = [50, 100, 200, 500];

  /** The preset amounts the server allows, so a chip is never one that would be refused. */
  static presets(rules: OneTimeRules): number[] {
    return OneTimeChoices.PRESETS.filter((n) => n >= rules.min_credits && n <= rules.max_credits);
  }

  /** The amount from a chip or the box: the chip when one is picked, else the box's text checked against the limits. */
  static amount(picked: number | null, custom: string, rules: OneTimeRules): { credits: number; paise: number } | { message: string } | null {
    if (picked !== null) return { credits: picked, paise: picked * rules.price_paise_per_credit };
    if (!custom.trim()) return null;
    const checked = PlanWords.check(custom, rules);
    return checked.ok ? { credits: checked.credits, paise: checked.paise } : { message: checked.message };
  }

  static total(credits: number, rules: OneTimeRules): string {
    return `${PlanWords.rupees(credits * rules.price_paise_per_credit)} for ${credits} credits`;
  }
}

/** How many periods of a plan to buy at once (weeks of Weekly Pro). */
export class PlanQuantity {
  static clamp(plan: Plan, quantity: number): number {
    return Math.min(Math.max(Math.trunc(quantity) || 1, 1), Math.max(plan.max_quantity, 1));
  }

  static canChoose(plan: Plan): boolean {
    return plan.max_quantity > 1;
  }

  static total(plan: Plan, quantity: number): { paise: number; credits: number } {
    const n = PlanQuantity.clamp(plan, quantity);
    return { paise: plan.price_paise * n, credits: plan.credits * n };
  }

  /** "2 weeks" for a plan by the week, nothing for one bought whole. */
  static words(plan: Plan, quantity: number): string {
    if (!PlanQuantity.canChoose(plan)) return "";
    const n = PlanQuantity.clamp(plan, quantity);
    return n === 1 ? "1 week" : `${n} weeks`;
  }
}
