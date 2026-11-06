import type { Quote } from "./types";

/**
 * A price as a learner reads it. The numbers are the server's; this only puts them in words, and never says anything about
 * how they were reached (no hold, ledger or bucket: a learner has credits, and things cost credits).
 */
export class CostWords {
  /** Shown on the mastery choice of a lesson, never on a study-sheets journey (plan D7). */
  static readonly HALF_BACK = "You already know this. Here's half your credits back.";
  static readonly EXEMPT = "Free for you";

  /** "1 credit", "3 credits". */
  static credits(count: number): string {
    return `${count} ${count === 1 ? "credit" : "credits"}`;
  }

  /** What to put on the button: one price, or the stages of a journey with the total. */
  static of(quote: Quote): string {
    if (quote.exempt) return CostWords.EXEMPT;
    if (quote.total === 0) return "Free";
    if (quote.later > 0 && quote.due_now > 0) {
      return `${CostWords.credits(quote.due_now)} now, ${quote.later} after the Quick check · ${CostWords.credits(quote.total)} in all`;
    }
    return CostWords.credits(quote.total);
  }

  /** The short form for a badge: the total, or "Free". */
  static short(quote: Quote): string {
    if (quote.exempt) return CostWords.EXEMPT;
    return quote.total === 0 ? "Free" : CostWords.credits(quote.total);
  }

  /** What the price is made of, for a hint under the button: "Quick check 3 + Your lesson, after the Quick check 7". */
  static breakdown(quote: Quote): string {
    return [...quote.lines, ...quote.later_lines]
      .filter((line) => line.credits > 0)
      .map((line) => `${line.label} ${line.credits}`)
      .join(" + ");
  }

  /** Whether the learner can pay what is due now. A journey is paid in stages, so only the first stage must be there. */
  static affordable(quote: Quote, balance: number): boolean {
    return quote.exempt || balance >= quote.due_now;
  }

  /** "You have 4 credits; this needs 10." for a label next to a button that will be refused. */
  static shortBy(quote: Quote, balance: number): string {
    return `You have ${CostWords.credits(balance)}; this needs ${CostWords.credits(quote.due_now)}.`;
  }
}
