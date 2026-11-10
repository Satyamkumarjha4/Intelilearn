import { PlanWords } from "@/lib/credits/plan-words";
import type { CostRange, PublicPlan, PublicPricing } from "@/lib/landing/types";

/** A line of a plan card: some words, and the part of them to show bold. */
export type CardLine = { bold?: string; text: string };

export type PlanCard = {
  key: string;
  name: string;
  /** "₹199" */
  price: string;
  /** "/ 28 days", or null for the free plan. */
  per: string | null;
  tagline: string | null;
  lines: CardLine[];
  featured: boolean;
  badge: string | null;
  cta: { label: string; href: string };
};

export type CostRow = { label: string; value: string };

const TAGLINES: Record<string, string> = {
  free: "Try Socra on your first topics.",
  weekly_pro: "For a week of exam prep.",
  monthly_pro: "For learning a little every day.",
  pro_plus: "For heavy study and exam season.",
};

/**
 * The pricing section's words, worked out from what `GET /api/public/pricing` says and nothing else: no price, credit
 * count or "about N lessons" is written here, so a price edited in the console is the price on the page. A number the
 * server could not give (null) is left out, never guessed. Claims about one plan against another ("the lowest price per
 * credit", "less than half a top-up") are made only when the numbers show them.
 */
export class PricingWords {
  static readonly FEATURED = "monthly_pro";
  static readonly BADGE = "Best value for regular study";

  static rupees(paise: number): string {
    return PlanWords.rupees(paise);
  }

  /** "₹0.40 a credit": paise a credit are often fractions of a rupee. */
  static perCredit(paise: number): string {
    return `${PlanWords.rupees(paise)} a credit`;
  }

  /** "About 10 full lessons", or null when the server could not say. */
  static aboutLessons(count: number | null): string | null {
    if (count === null) return null;
    return `About ${count} full ${count === 1 ? "lesson" : "lessons"}`;
  }

  /** "2–3", or "2" when the range is a single price. */
  static range(range: CostRange): string {
    return range.min === range.max ? `${range.min}` : `${range.min}–${range.max}`;
  }

  /** How long something lasts, as a phrase: "a year", "a week", "28 days". */
  static lasts(days: number): string {
    if (days === 365) return "a year";
    if (days === 7) return "a week";
    return `${days} days`;
  }

  /** "+1 credit", "+10 credits". */
  static plus(count: number): string {
    return `+${count} ${count === 1 ? "credit" : "credits"}`;
  }

  /** Whether the page may promise free credits: only when the server says there are some. */
  static hasFreeCredits(pricing: PublicPricing | null): pricing is PublicPricing {
    return !!pricing && pricing.signup_credits > 0;
  }

  /** The hero and final buttons: "Start with 30 free credits", or just "Start free" when there is nothing to promise. */
  static startLabel(pricing: PublicPricing | null): string {
    return PricingWords.hasFreeCredits(pricing) ? `Start with ${pricing.signup_credits} free credits` : "Start free";
  }

  /** What credits buy, from the live prices; a price the server could not give is left out. */
  static costRows(pricing: PublicPricing): CostRow[] {
    const rows: [string, string | null][] = [
      ["Full lesson with its Test", pricing.lesson_credits === null ? null : `${pricing.lesson_credits}`],
      ["Retake, new questions", pricing.retake_credits === null ? null : `${pricing.retake_credits}`],
      ["Cheat or revision sheet", pricing.sheet_credits ? PricingWords.range(pricing.sheet_credits) : null],
      ["Quick quiz", pricing.quiz_credits ? PricingWords.range(pricing.quiz_credits) : null],
    ];
    return rows.flatMap(([label, value]) => (value === null ? [] : [{ label, value }]));
  }

  /** The line under the plans about a top-up, or null when top-ups are not on. */
  static topUp(pricing: PublicPricing): { bold: string; text: string } | null {
    const rules = pricing.one_time;
    if (!rules) return null;
    return {
      bold: "Need just a few more?",
      text: ` Top up at ${PlanWords.rupees(rules.price_paise_per_credit)} a credit, ${rules.min_credits} or more at a time, valid for ${PricingWords.lasts(rules.valid_days)}, on top of any plan.`,
    };
  }

  /** The cards, Free first and then each plan in the server's order. `signedIn` points the buttons at the app, not at sign-up. */
  static cards(pricing: PublicPricing, signedIn: boolean, registerHref: string): PlanCard[] {
    const cheapest = PricingWords.cheapestPerCredit(pricing.plans);
    const free: PlanCard = {
      key: "free",
      name: "Free",
      price: PlanWords.rupees(0),
      per: null,
      tagline: TAGLINES.free,
      lines: PricingWords.freeLines(pricing),
      featured: false,
      badge: null,
      cta: signedIn ? { label: "Go to my lessons", href: "/lessons" } : { label: "Start free", href: registerHref },
    };
    const paid = pricing.plans.map((plan): PlanCard => {
      const featured = plan.key === PricingWords.FEATURED;
      return {
        key: plan.key,
        name: plan.name,
        price: PlanWords.rupees(plan.price_paise),
        per: `/ ${PlanWords.span(plan.period_days)}`,
        tagline: TAGLINES[plan.key] ?? null,
        lines: PricingWords.planLines(plan, pricing, cheapest),
        featured,
        badge: featured ? PricingWords.BADGE : null,
        cta: { label: `Choose ${plan.name}`, href: signedIn ? "/buy" : registerHref },
      };
    });
    return [free, ...paid];
  }

  private static freeLines(pricing: PublicPricing): CardLine[] {
    const lines: CardLine[] = [{ bold: `${pricing.signup_credits} credits`, text: " that never expire" }];
    const about = PricingWords.aboutLessons(pricing.signup_about_lessons);
    if (about) lines.push({ text: about });
    const earn = [`${PricingWords.plus(pricing.daily_credits)} a day you study`, `${PricingWords.plus(pricing.weekly_streak_bonus)} every 7-day streak`];
    if (pricing.monthly_streak_bonus > 0) earn.push(`${PricingWords.plus(pricing.monthly_streak_bonus)} more at 28 days`);
    lines.push({ text: earn.join(", ") });
    return lines;
  }

  private static planLines(plan: PublicPlan, pricing: PublicPricing, cheapest: string | null): CardLine[] {
    const span = PlanWords.span(plan.period_days);
    const weekly = plan.period_days === 7;
    const lines: CardLine[] = [{ bold: `${plan.credits} credits`, text: weekly ? " a week" : ` for ${span}` }];
    const about = PricingWords.aboutLessons(plan.about_lessons);
    if (about) lines.push({ text: weekly ? `${about} a week` : about });
    const extra = PricingWords.comparison(plan, pricing, cheapest);
    if (extra) lines.push({ text: extra });
    return lines;
  }

  /** The third line of a plan, only ever one the numbers back: several weeks, the lowest price a credit, or a top-up compared. */
  private static comparison(plan: PublicPlan, pricing: PublicPricing, cheapest: string | null): string | null {
    if (plan.max_quantity > 1) return "Buy several weeks; they arrive one at a time";
    if (cheapest === plan.key) return "The lowest price per credit";
    const topUp = pricing.one_time?.price_paise_per_credit;
    if (plan.price_paise_per_credit !== null && topUp && plan.price_paise_per_credit < topUp) {
      return plan.price_paise_per_credit * 2 < topUp ? "Less than half the price per credit of a top-up" : "Cheaper per credit than a top-up";
    }
    return null;
  }

  /** The key of the plan with the lowest price a credit, or null when two share it (or there is only one). */
  private static cheapestPerCredit(plans: PublicPlan[]): string | null {
    const priced = plans.filter((plan): plan is PublicPlan & { price_paise_per_credit: number } => plan.price_paise_per_credit !== null);
    if (priced.length < 2) return null;
    const lowest = Math.min(...priced.map((plan) => plan.price_paise_per_credit));
    const holders = priced.filter((plan) => plan.price_paise_per_credit === lowest);
    return holders.length === 1 ? holders[0].key : null;
  }
}
