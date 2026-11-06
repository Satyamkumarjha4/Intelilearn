/**
 * Unit under test: `CostWords`, a price as a learner reads it.
 *
 * Why: the number is the server's, but the sentence around it is the product's. A learner must read "credits", never how
 * a price was made; a lesson paid in two stages must say so; and a learner who is not charged must not be shown a price
 * that will not be taken.
 *
 * Use cases:
 * - one credit is singular
 * - a price reads as credits; nothing due reads "Free"; an exempt learner reads "Free for you"
 * - a journey with a part later says what is due now, what follows, and the total
 * - the short form is the total only
 * - the breakdown lists the lines of both stages that cost something
 * - whether a learner can afford a price looks at what is due now only; an exempt learner always can
 * - being short reads as what there is and what is needed
 * - the half-back sentence for the mastery choice is the product's, word for word
 */
import { describe, expect, test } from "bun:test";

import { CostWords } from "./cost-words";
import type { Quote } from "./types";

const quote = (over: Partial<Quote> = {}): Quote => ({
  action: "lesson.create", lines: [{ key: "k", label: "Quick check", credits: 3 }], due_now: 3, later_lines: [], later: 0, total: 3, exempt: false, ...over,
});

describe("a price", () => {
  test("one credit is singular", () => {
    expect(CostWords.credits(1)).toBe("1 credit");
    expect(CostWords.credits(0)).toBe("0 credits");
    expect(CostWords.credits(7)).toBe("7 credits");
  });

  test("reads as credits, free when nothing is due, and free for an exempt learner", () => {
    expect(CostWords.of(quote())).toBe("3 credits");
    expect(CostWords.of(quote({ due_now: 0, total: 0, lines: [] }))).toBe("Free");
    expect(CostWords.of(quote({ exempt: true }))).toBe("Free for you");
  });

  test("a journey says what is due now, what follows and the total", () => {
    const journey = quote({ later: 7, total: 10, later_lines: [{ key: "r", label: "Your lesson", credits: 7 }] });

    expect(CostWords.of(journey)).toBe("3 credits now, 7 after the Quick check · 10 credits in all");
    expect(CostWords.short(journey)).toBe("10 credits");
  });

  test("the breakdown lists the lines of both stages that cost something", () => {
    const journey = quote({
      later: 7, total: 10, later_lines: [{ key: "r", label: "Your lesson", credits: 7 }, { key: "z", label: "Nothing", credits: 0 }],
    });

    expect(CostWords.breakdown(journey)).toBe("Quick check 3 + Your lesson 7");
  });
});

describe("affording it", () => {
  test("looks at what is due now only", () => {
    const journey = quote({ later: 7, total: 10 });

    expect(CostWords.affordable(journey, 3)).toBe(true);
    expect(CostWords.affordable(journey, 2)).toBe(false);
  });

  test("an exempt learner always can", () => {
    expect(CostWords.affordable(quote({ exempt: true }), 0)).toBe(true);
  });

  test("being short reads as what there is and what is needed", () => {
    expect(CostWords.shortBy(quote(), 1)).toBe("You have 1 credit; this needs 3 credits.");
  });
});

test("the half-back sentence is the product's, word for word", () => {
  expect(CostWords.HALF_BACK).toBe("You already know this. Here's half your credits back.");
});
