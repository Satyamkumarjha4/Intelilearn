import { HERO_EYEBROWS } from "@/lib/landing-content";
import type { DemoQuestion } from "@/lib/types";

/** An option's index, or "I don't know". */
export const DONT_KNOW_ANSWER = "dont_know" as const;
export type HeroAnswer = number | typeof DONT_KNOW_ANSWER;

export type HeroResultCopy = {
  eyebrow: string;
  /** How many of the five level segments are lit. */
  level: number;
  levelLabel: string;
  startsWith: string;
};

/** What the landing page's try-it card says once a visitor has answered: from the question and its two outcomes. */
export class HeroDemo {
  static isAnswer(question: DemoQuestion, value: HeroAnswer): boolean {
    return value === DONT_KNOW_ANSWER || (Number.isInteger(value) && value >= 0 && value < question.options.length);
  }

  static isRight(question: DemoQuestion, answer: HeroAnswer): boolean {
    return answer === question.correct_index;
  }

  /** "I don't know" is the answer the product asks for, so it gets the same warmth as a wrong one, never a "wrong". */
  static resultFor(question: DemoQuestion, answer: HeroAnswer): HeroResultCopy {
    const right = HeroDemo.isRight(question, answer);
    const outcome = right ? question.outcome_right : question.outcome_wrong;
    return {
      eyebrow: right ? HERO_EYEBROWS.right : HERO_EYEBROWS.notYet,
      level: outcome.level,
      levelLabel: outcome.level_label,
      startsWith: outcome.lesson_start,
    };
  }
}
