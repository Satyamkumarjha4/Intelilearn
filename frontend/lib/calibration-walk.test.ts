/**
 * Unit under test: `CalibrationWalk`, the learner's side of the calibration warm-up.
 *
 * Why: the warm-up is five questions whose answers are final and whose order the server decides. The screen must show the
 * server's question and nothing else, never send one answer twice, and recover when the walk has moved on (another tab,
 * a double click) instead of leaving the learner on a question that can no longer be answered.
 *
 * Use cases:
 * - starts by asking the server which question is next, and shows it with its place in the walk
 * - an answer is sent for the question on screen, and what comes back is shown; "I don't know" is a null answer
 * - after the last answer the walk is done and says the level
 * - a second answer while the first is being saved is ignored
 * - an answer the server refuses because the walk moved on (409) shows where the walk really is
 * - any other failure is shown in words, and the state can be tried again with `start`
 * - every change is reported, so the screen can follow
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { CalibrationWalk, type WalkState } from "./calibration-walk";
import type { Calibration } from "./types";

const asking = (id: string, step: number): Calibration => ({
  done: false, step, total: 5, question: { id, question: `Question ${id}?`, options: ["a", "b", "c", "d"] },
});

function fakeApi(script: (Calibration | Error)[]) {
  const sent: [string, number | null][] = [];
  const next = () => {
    const item = script.shift();
    if (item === undefined) throw new Error("nothing scripted");
    return item instanceof Error ? Promise.reject(item) : Promise.resolve(item);
  };
  return {
    sent,
    api: {
      calibration: async () => next(),
      answerCalibration: async (_id: string, question: string, answer: number | null) => {
        sent.push([question, answer]);
        return next();
      },
    },
  };
}

describe("the walk", () => {
  test("starts with the question the server says is next", async () => {
    const { api } = fakeApi([asking("q5", 1)]);
    const walk = new CalibrationWalk(api, "quiz");

    const state = await walk.start();

    expect(state).toEqual({ kind: "asking", step: 1, total: 5, question: { id: "q5", question: "Question q5?", options: ["a", "b", "c", "d"] }, saving: false });
  });

  test("sends the answer for the question on screen and shows what comes back", async () => {
    const { api, sent } = fakeApi([asking("q5", 1), asking("q7", 2), asking("q8", 3)]);
    const walk = new CalibrationWalk(api, "quiz");
    await walk.start();

    await walk.answer(2);
    const state = await walk.answer(null);

    expect(sent).toEqual([["q5", 2], ["q7", null]]);
    expect(state).toMatchObject({ kind: "asking", step: 3 });
  });

  test("after the last answer it is done and says the level", async () => {
    const { api } = fakeApi([asking("q5", 5), { done: true, level: "expert" }]);
    const walk = new CalibrationWalk(api, "quiz");
    await walk.start();

    expect(await walk.answer(0)).toEqual({ kind: "done", level: "expert" });
  });

  test("a second answer while the first is being saved is ignored", async () => {
    const { api, sent } = fakeApi([asking("q5", 1), asking("q7", 2)]);
    const walk = new CalibrationWalk(api, "quiz");
    await walk.start();

    const first = walk.answer(1);
    const second = walk.answer(2);
    await Promise.all([first, second]);

    expect(sent).toEqual([["q5", 1]]);
  });

  test("an answer with no question on screen sends nothing", async () => {
    const { api, sent } = fakeApi([]);

    expect((await new CalibrationWalk(api, "quiz").answer(1)).kind).toBe("loading");
    expect(sent).toEqual([]);
  });
});

describe("when something goes wrong", () => {
  test("a walk that moved on shows where it really is", async () => {
    const stale = new ApiError(409, "not_current", "That is not the question you are on.");
    const { api } = fakeApi([asking("q5", 1), stale, asking("q7", 2)]);
    const walk = new CalibrationWalk(api, "quiz");
    await walk.start();

    const state = await walk.answer(1);

    expect(state).toMatchObject({ kind: "asking", step: 2, question: { id: "q7" } });
  });

  test("any other failure is shown in words and the walk can be started again", async () => {
    const { api } = fakeApi([new ApiError(500, "error", "Something broke."), asking("q5", 1)]);
    const walk = new CalibrationWalk(api, "quiz");

    expect(await walk.start()).toEqual({ kind: "error", message: "Something broke." });
    expect((await walk.start()).kind).toBe("asking");
  });

  test("an error that is not the API's gets words of ours", async () => {
    const { api } = fakeApi([new TypeError("network")]);

    expect(await new CalibrationWalk(api, "quiz").start()).toEqual({ kind: "error", message: "We couldn't load the next question. Please try again." });
  });
});

test("every change is reported", async () => {
  const seen: WalkState["kind"][] = [];
  const { api } = fakeApi([asking("q5", 1), { done: true, level: "foundation" }]);
  const walk = new CalibrationWalk(api, "quiz", (state) => seen.push(state.kind));

  await walk.start();
  await walk.answer(0);

  expect(seen).toEqual(["asking", "asking", "done"]); // asking, then saving, then done
});
