import { ShortDate } from "./short-date";
import type { OneTimeRules, Plan, PlanPeriod, Plans } from "./types";

/** Whole credits asked for, or why not. */
export type AmountCheck = { ok: true; credits: number; paise: number } | { ok: false; message: string };

/**
 * Plans and prices in a learner's words. Money is paise on the wire (100 paise = 1 rupee, tax included) and is only
 * formatted here; the server works out every price it charges, and so does not trust a number sent from this page.
 */
export class PlanWords {
  static rupees(paise: number): string {
    const rupees = paise / 100;
    const whole = Number.isInteger(rupees);
    return `₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 }).format(rupees)}`;
  }

  /** "week" for 7 days, else "28 days". */
  static span(days: number): string {
    return days === 7 ? "week" : days === 1 ? "day" : `${days} days`;
  }

  /** "₹49 a week", "₹199 for 28 days", "₹1 a credit". */
  static price(plan: Plan): string {
    const money = PlanWords.rupees(plan.price_paise);
    if (plan.kind === "one_time") return `${money} a credit`;
    return plan.period_days === 7 ? `${money} a week` : `${money} for ${PlanWords.span(plan.period_days)}`;
  }

  /** "100 credits every week". */
  static gives(plan: Plan): string {
    return `${plan.credits} credits every ${PlanWords.span(plan.period_days)}`;
  }

  /** The plans that come every period, in the order the server sorted them. */
  static recurring(plans: Plans): Plan[] {
    return plans.plans.filter((plan) => plan.kind === "recurring");
  }

  /** A running or waiting period as one line. */
  static period(period: PlanPeriod): string {
    const when = period.status === "active" ? `running until ${PlanWords.day(period.ends_at)}` : `starts ${PlanWords.day(period.starts_at)}`;
    return `${period.plan_name}: ${period.credits} credits, ${when}`;
  }

  static queue(queue: { open: number; limit: number }): string {
    return `${queue.open} of ${queue.limit} plan periods lined up`;
  }

  /** "Fri 14 Nov". */
  static day(at: string): string {
    return ShortDate.of(new Date(at));
  }

  /** What bought credits cost for an amount typed in a box; nothing is sent until the buy flow opens (phase 10.6). */
  static check(text: string, rules: OneTimeRules): AmountCheck {
    const trimmed = text.trim();
    if (!/^\d+$/.test(trimmed)) return { ok: false, message: "Enter a whole number of credits." };
    const credits = Number(trimmed);
    if (credits < rules.min_credits) return { ok: false, message: `The smallest amount is ${rules.min_credits} credits.` };
    if (credits > rules.max_credits) return { ok: false, message: `The most you can buy at once is ${rules.max_credits} credits.` };
    return { ok: true, credits, paise: credits * rules.price_paise_per_credit };
  }

  /** How long bought credits last: "a year", "90 days". */
  static valid(days: number): string {
    if (days === 365) return "a year";
    return `${days} days`;
  }
}

/** Whether buying is switched on. The pages are a shell until the payment flow is built (phase 10.6). */
export class BuyState {
  static readonly OPEN = false;
  static readonly CLOSED_TEXT = "Buying isn't open yet";
  static readonly CLOSED_HELP = "You can see what's coming. We'll let you know here as soon as you can buy credits.";
}
