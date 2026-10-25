/**
 * Unit under test: `HeroDemo`, what the landing page's try-it card says after a visitor answers.
 *
 * Why: the card is the first taste of the product. A right answer and a not-yet answer must read differently, and
 * "I don't know" must be treated as the useful answer the product says it is: never as a wrong one. The question, its
 * right answer and where the lesson would begin now come with the question, so none of it can be assumed.
 *
 * Use cases:
 * - the question's right option is judged right; the other options and "I don't know" are not, whichever option is right
 * - an option that does not exist is not an answer at all
 * - a right answer gets the "that's right" copy and the question's right outcome; a wrong one the encouraging copy and
 *   the wrong outcome
 * - a wrong answer and "I don't know" get exactly the same result
 * - the result carries the level, its name and where the lesson would begin, as the question says
 */
import { describe, expect, test } from "bun:test";

import { DONT_KNOW_ANSWER, HeroDemo } from "./hero-demo";
import { DemoQuestions } from "./demo-question";
import type { DemoQuestion } from "./types";

const question: DemoQuestion = {
  ...DemoQuestions.fallback(),
  id: 5,
  options: ["a", "b", "c"],
  correct_index: 2,
  outcome_right: { level: 4, level_label: "Confident", lesson_start: "Right start." },
  outcome_wrong: { level: 2, level_label: "Building up", lesson_start: "Wrong start." },
};

describe("HeroDemo", () => {
  test("only the question's right option is right, wherever it is", () => {
    expect(HeroDemo.isRight(question, 2)).toBe(true);
    expect([0, 1, DONT_KNOW_ANSWER].some((answer) => HeroDemo.isRight(question, answer))).toBe(false);
    expect(HeroDemo.isRight({ ...question, correct_index: 0 }, 0)).toBe(true);
  });

  test.each([[-1], [3], [1.5]])("option %p is not an answer", (option) => {
    expect(HeroDemo.isAnswer(question, option)).toBe(false);
  });

  test("options and I don't know are answers", () => {
    expect([0, 1, 2, DONT_KNOW_ANSWER].every((answer) => HeroDemo.isAnswer(question, answer))).toBe(true);
  });

  test("a right answer is told so and gets the right outcome; a wrong one is encouraged and gets the wrong outcome", () => {
    expect(HeroDemo.resultFor(question, 2)).toEqual({
      eyebrow: "Nice, that's right",
      level: 4,
      levelLabel: "Confident",
      startsWith: "Right start.",
    });
    expect(HeroDemo.resultFor(question, 0)).toEqual({
      eyebrow: "No problem, that's what the check is for",
      level: 2,
      levelLabel: "Building up",
      startsWith: "Wrong start.",
    });
  });

  test("a wrong answer and I don't know get the same result", () => {
    expect(HeroDemo.resultFor(question, DONT_KNOW_ANSWER)).toEqual(HeroDemo.resultFor(question, 1));
  });
});
