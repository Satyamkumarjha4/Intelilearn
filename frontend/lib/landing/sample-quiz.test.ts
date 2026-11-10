/**
 * Unit under test: `SampleQuiz`, the landing page's sample Quick check (three fixed trigonometry questions).
 *
 * Why: it is the first thing a visitor can touch, and it stands for the real Quick check, so it must score exactly,
 * give the same feedback every time, and never get stuck (a double click, a click after the answer, an early "next").
 * It makes no network or model call at all, which is why it is plain code a test can run end to end.
 *
 * Use cases:
 * - it starts on question 1 of 3, nothing picked, no score, no feedback, with the progress bar empty
 * - picking the right option scores one and says "Right." with the reason; a wrong one says "Not quite." and scores none
 * - after an answer the right option shows as right, a wrong pick as wrong, and the others fade; before one all are open
 * - the first pick counts: a second pick, or one that is not an option, changes nothing
 * - "next" before an answer does nothing; after one it moves on, and after the last it shows the result
 * - the progress bar counts a question once it is answered (1/3 after the first answer, full after the last)
 * - the result names the level for the score (0 Beginner, 1 Foundation, 2 Proficient, 3 Expert) with its three pages
 * - the button on the last question reads "See my lesson"
 * - restart goes back to the start with the score cleared; a moved quiz does not change the one it came from
 */
import { describe, expect, test } from "bun:test";

import { SampleQuiz } from "./sample-quiz";
import { SAMPLE_LEVELS, SAMPLE_QUESTIONS } from "./sample-quiz-content";

const right = (quiz: SampleQuiz) => quiz.pick(quiz.current.answer);
const wrong = (quiz: SampleQuiz) => quiz.pick((quiz.current.answer + 1) % quiz.current.options.length);

/** Play all three questions, answering right where `rights[i]` is true. */
function play(rights: boolean[]): SampleQuiz {
  let quiz = SampleQuiz.start();
  for (const ok of rights) quiz = (ok ? right(quiz) : wrong(quiz)).next();
  return quiz;
}

describe("the start", () => {
  test("it opens on question 1 of 3 with nothing picked", () => {
    const quiz = SampleQuiz.start();

    expect([quiz.number, quiz.total, quiz.picked, quiz.answered, quiz.done, quiz.score]).toEqual([1, 3, null, false, false, 0]);
    expect(quiz.feedback).toBe("");
    expect(quiz.progress).toBe(0);
    expect(quiz.current.question).toBe(SAMPLE_QUESTIONS[0].question);
  });

  test("every question has three options and an answer among them", () => {
    for (const q of SAMPLE_QUESTIONS) {
      expect(q.options).toHaveLength(3);
      expect(q.answer).toBeGreaterThanOrEqual(0);
      expect(q.answer).toBeLessThan(3);
      expect(q.why.length).toBeGreaterThan(0);
    }
  });
});

describe("answering", () => {
  test("the right option scores one and says right, with the reason", () => {
    const quiz = right(SampleQuiz.start());

    expect(quiz.score).toBe(1);
    expect(quiz.feedback).toBe(`Right. ${SAMPLE_QUESTIONS[0].why}`);
  });

  test("a wrong option scores nothing and says not quite, with the reason", () => {
    const quiz = wrong(SampleQuiz.start());

    expect(quiz.score).toBe(0);
    expect(quiz.feedback).toBe(`Not quite. ${SAMPLE_QUESTIONS[0].why}`);
  });

  test("after an answer the right option is right, a wrong pick is wrong and the rest fade", () => {
    const start = SampleQuiz.start();
    expect([0, 1, 2].map((o) => start.optionState(o))).toEqual(["open", "open", "open"]);

    const quiz = start.pick(1); // the answer to question 1 is option 0

    expect([0, 1, 2].map((o) => quiz.optionState(o))).toEqual(["right", "wrong", "rest"]);
  });

  test("the first pick counts: a second pick changes nothing", () => {
    const first = wrong(SampleQuiz.start());

    const again = first.pick(first.current.answer);

    expect(again.picked).toBe(first.picked);
    expect(again.score).toBe(0);
  });

  test.each([-1, 3, 1.5, Number.NaN])("a pick of %p is not an option and changes nothing", (option) => {
    const quiz = SampleQuiz.start().pick(option);

    expect(quiz.answered).toBe(false);
    expect(quiz.score).toBe(0);
  });
});

describe("moving on", () => {
  test("next before an answer does nothing", () => {
    expect(SampleQuiz.start().next().number).toBe(1);
  });

  test("next after an answer goes to the next question with nothing picked", () => {
    const quiz = right(SampleQuiz.start()).next();

    expect([quiz.number, quiz.picked, quiz.done]).toEqual([2, null, false]);
    expect(quiz.current.question).toBe(SAMPLE_QUESTIONS[1].question);
  });

  test("next after the last answer shows the result", () => {
    expect(play([true, true, true]).done).toBe(true);
  });

  test("the button says next question, and on the last question see my lesson", () => {
    const first = SampleQuiz.start();
    const last = play([true, true]);

    expect([first.nextLabel, last.nextLabel]).toEqual(["Next question", "See my lesson"]);
  });

  test("the progress bar counts a question once it is answered", () => {
    const start = SampleQuiz.start();

    expect(start.progress).toBe(0);
    expect(right(start).progress).toBeCloseTo(1 / 3);
    expect(right(start).next().progress).toBeCloseTo(1 / 3);
    expect(right(play([true, true])).progress).toBe(1);
  });

  test("a finished quiz ignores further picks and moves", () => {
    const done = play([true, false, true]);

    expect(done.pick(0)).toBe(done);
    expect(done.next()).toBe(done);
  });
});

describe("the result", () => {
  test.each([
    [[false, false, false], 0, "Beginner"],
    [[true, false, false], 1, "Foundation"],
    [[true, false, true], 2, "Proficient"],
    [[true, true, true], 3, "Expert"],
  ])("answers %p score %i and give the level %s", (rights, score, name) => {
    const quiz = play(rights);

    expect(quiz.score).toBe(score);
    expect(quiz.level.name).toBe(name);
    expect(quiz.level.pages).toHaveLength(3);
    expect(quiz.level.snippet.length).toBeGreaterThan(0);
  });

  test("the four levels are in order from Beginner to Expert", () => {
    expect(SAMPLE_LEVELS.map((l) => l.name)).toEqual(["Beginner", "Foundation", "Proficient", "Expert"]);
  });
});

describe("restart", () => {
  test("it goes back to the start with the score cleared", () => {
    const restarted = play([true, true, true]).restart();

    expect([restarted.number, restarted.score, restarted.done, restarted.picked]).toEqual([1, 0, false, null]);
  });

  test("moving a quiz does not change the one it came from", () => {
    const start = SampleQuiz.start();

    right(start).next();

    expect([start.number, start.score, start.picked]).toEqual([1, 0, null]);
  });
});
