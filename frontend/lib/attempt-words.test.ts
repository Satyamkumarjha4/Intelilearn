/**
 * Unit under test: `AttemptWords`, the words of the screen that takes an attempt.
 *
 * Why: one runner serves the lesson's test and the quick quiz. A learner who is taking a quick quiz must never be told
 * they are handing in a "test" (the two are different things, and the app keeps their names apart), and the test must
 * keep its own words exactly.
 *
 * Use cases:
 * - the test keeps its words: "Test", "Marking your test", "Hand in your test?"
 * - the quick quiz says quiz everywhere, and calls itself "Quick quiz"
 * - both promise the score straight away and a new try later
 */
import { describe, expect, test } from "bun:test";

import { AttemptWords } from "./attempt-words";

describe("the test", () => {
  const words = AttemptWords.of("test");

  test("keeps its words", () => {
    expect([words.title, words.subtitle, words.marking, words.confirmTitle, words.failedTitle, words.handIn, words.couldNotHandIn]).toEqual([
      "Test", "Show what you learned", "Marking your test", "Hand in your test?", "We couldn't hand in your test", "Hand in my test",
      "Could not hand in your test.",
    ]);
  });
});

describe("the quick quiz", () => {
  const words = AttemptWords.of("quiz");

  test("says quiz everywhere", () => {
    expect([words.title, words.marking, words.confirmTitle, words.failedTitle, words.handIn, words.couldNotHandIn, words.cardsLabel]).toEqual([
      "Quick quiz", "Marking your quiz", "Hand in your quiz?", "We couldn't hand in your quiz", "Hand in my quiz", "Could not hand in your quiz.",
      "Quiz questions",
    ]);
    expect(JSON.stringify(words)).not.toMatch(/\btest\b/i);
  });
});

test("both promise the score at once and a new try later", () => {
  for (const kind of ["test", "quiz"] as const) {
    expect(AttemptWords.of(kind).confirmText).toContain("score straight away");
    expect(AttemptWords.of(kind).confirmText).toContain("try again later with new questions");
  }
});
