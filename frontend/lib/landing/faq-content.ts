import { PricingWords } from "@/lib/landing/pricing-words";
import type { PublicPricing } from "@/lib/landing/types";

/** An answer is some words with, at most, a link to a page of ours. */
export type AnswerPart = string | { text: string; href: string };
export type FaqItem = { question: string; answer: AnswerPart[] };

/**
 * The eight questions of the landing page. An answer that quotes a number takes it from the pricing endpoint; when the
 * endpoint could not be read the answer says the same thing without the number, so the page never shows a figure it
 * cannot vouch for. Payment methods are never named: only that card and payment details stay with the provider.
 */
export class FaqContent {
  static items(pricing: PublicPricing | null): FaqItem[] {
    return [
      { question: "How does Socra know my level?", answer: [FaqContent.level(pricing)] },
      { question: "How do credits work?", answer: [FaqContent.credits(pricing)] },
      { question: "Is it free to start?", answer: [FaqContent.free(pricing)] },
      { question: "Do credits expire?", answer: [FaqContent.expiry(pricing)] },
      { question: "Will I be charged automatically?", answer: ["Never. Every plan is prepaid and nothing renews on its own."] },
      { question: "What if a lesson fails to build?", answer: ["You get your credits back automatically."] },
      { question: "Who is Socra for?", answer: ["School and college students, and anyone early in their career learning something new."] },
      {
        question: "Is my data private?",
        answer: [
          "Your lessons are yours. Card and other payment details stay with the payment provider and never reach us. Read the ",
          { text: "Privacy Policy", href: "/privacy" },
          ".",
        ],
      },
    ];
  }

  private static level(pricing: PublicPricing | null): string {
    const check = pricing ? `${pricing.quick_check_questions}-question Quick check` : "short Quick check";
    return `You answer a ${check}, or rate yourself with stars. Socra uses that to decide where your lesson starts and how deep it goes. Your Test score later tells it whether to suggest an easier or a more advanced lesson.`;
  }

  private static credits(pricing: PublicPricing | null): string {
    const parts: string[] = [];
    if (pricing) {
      if (pricing.lesson_credits !== null) parts.push(`a full lesson with its Test is ${pricing.lesson_credits}`);
      if (pricing.retake_credits !== null) parts.push(`a retake is ${pricing.retake_credits}`);
      if (pricing.sheet_credits) parts.push(`a sheet is ${PricingWords.range(pricing.sheet_credits).replace("–", " to ")}`);
      if (pricing.quiz_credits) parts.push(`a quick quiz is ${PricingWords.range(pricing.quiz_credits).replace("–", " to ")}`);
    }
    const prices = parts.length ? ` ${FaqContent.sentence(parts)}.` : "";
    return `Credits pay for what Socra makes for you.${prices} Every button shows its cost before you click.`;
  }

  private static free(pricing: PublicPricing | null): string {
    if (!pricing || pricing.signup_credits <= 0) return "Yes. You can sign up without a card and look around before you spend anything.";
    const lessons = pricing.signup_about_lessons === null ? "" : `, enough for about ${pricing.signup_about_lessons} full lessons`;
    return `Yes. You get ${pricing.signup_credits} credits when you sign up${lessons}, with no card needed.`;
  }

  private static expiry(pricing: PublicPricing | null): string {
    const signup = pricing ? `Your ${pricing.signup_credits} sign-up credits never do.` : "Your sign-up credits never do.";
    const earned = pricing ? `last ${pricing.bonus_valid_days} days` : "have a time limit";
    const bought = pricing?.one_time ? `last ${PricingWords.lasts(pricing.one_time.valid_days)}` : "have a time limit";
    return `${signup} Credits you earn ${earned}, credits you buy ${bought}, and plan credits last for their plan's period. We remind you before any run out.`;
  }

  /** "a, b, c and d" with a capital at the start: "A full lesson ... is 10, a retake is 2 and a sheet is 2 to 3". */
  private static sentence(parts: string[]): string {
    const text = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
}
