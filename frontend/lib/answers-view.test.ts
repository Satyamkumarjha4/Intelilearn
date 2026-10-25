/**
 * Unit under test: `AnswersView`, how an answered quick check is told in the read-only answers tab.
 *
 * Why: this is where a learner learns from a wrong answer. Marking their own wrong pick and the right answer, saying
 * "I don't know" kindly (not as an error), and never marking anything for someone who chose the right option, all
 * depend on a few small rules that are easy to get backwards.
 *
 * Use cases:
 * - the verdict is Correct, Not quite, or a kind line for "I don't know"
 * - each option is marked correct (the right one, always), wrong (only the learner's own wrong pick) or plain, and
 *   says whether it was the learner's pick
 * - "I don't know" picks no option
 * - a miss is shown in amber, never red (a quick check is not an exam), and "I don't know" is neutral
 * - the score reads "6 / 10"
 */
import { describe, expect, test } from "bun:test";

import { AnswersView } from "./answers-view";
import type { ReviewQuestion } from "./types";

const q = (over: Partial<ReviewQuestion> = {}): ReviewQuestion => ({
  id: "q1", band: "basic", question: "?", options: ["a", "b", "c", "d"], correct_index: 1, explanation: "", answer: 1, correct: true, ...over,
});

describe("verdict", () => {
  test.each([
    [q(), "right", "Correct"],
    [q({ answer: 3, correct: false }), "wrong", "Not quite"],
    [q({ answer: "dont_know", correct: false }), "unsure", "You said “I don't know”"],
  ] as const)("%#", (question, kind, label) => {
    expect(AnswersView.verdict(question)).toEqual({ kind, label });
  });
});

describe("option", () => {
  test("the right answer is marked, and the learner's wrong pick too", () => {
    const question = q({ answer: 3, correct: false });

    expect([0, 1, 2, 3].map((i) => AnswersView.option(question, i))).toEqual([
      { tone: "plain", picked: false },
      { tone: "correct", picked: false },
      { tone: "plain", picked: false },
      { tone: "wrong", picked: true },
    ]);
  });

  test("a right pick is marked correct and picked, and nothing is wrong", () => {
    const tones = [0, 1, 2, 3].map((i) => AnswersView.option(q(), i));

    expect(tones[1]).toEqual({ tone: "correct", picked: true });
    expect(tones.filter((t) => t.tone === "wrong")).toEqual([]);
  });

  test("I don't know picks nothing, and the right answer is still shown", () => {
    const tones = [0, 1, 2, 3].map((i) => AnswersView.option(q({ answer: "dont_know", correct: false }), i));

    expect(tones.some((t) => t.picked)).toBe(false);
    expect(tones[1].tone).toBe("correct");
  });
});

test("the score reads correct over total", () => {
  expect(AnswersView.score({ correct: 6, total: 10, dont_know: 1, by_band: {} })).toBe("6 / 10");
});

describe("badge", () => {
  test.each([
    ["right", "success"],
    ["wrong", "marigold"],
    ["unsure", "secondary"],
  ] as const)("%s is shown as %s", (kind, variant) => {
    expect(AnswersView.badge(kind)).toBe(variant);
  });
});
