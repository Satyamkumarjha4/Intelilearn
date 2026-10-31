/**
 * Unit under test: `FollowupMaker`, what happens when a learner presses "Make a Foundation lesson" (or the Advanced one).
 *
 * Why: the server makes at most one follow-up of each level, so a second press, a stale offer or a second tab all end in
 * "it already exists". If that were shown as an error the learner would be told something went wrong when what they
 * wanted is one tap away; and if a refusal or a rate limit were shown in the machinery's words they would not know what to do.
 *
 * Use cases:
 * - a lesson that was made opens the new lesson
 * - "it already exists" is not a failure: the lesson that exists is opened, and nothing else is asked
 * - a 409 that is not "already exists", or one that names no lesson, is a failure with words
 * - a refused action is told in its own words; too many lessons, an unset-up helper and a lesson that is not ready each say
 *   what to do; anything else says it could not be made
 * - the words name no status code or machinery
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { FollowupMaker } from "./followup-maker";
import type { FollowupLevel } from "./types";

const maker = (reply: () => Promise<{ lesson_id: string; run_id: string }>) => {
  const calls: [string, FollowupLevel][] = [];
  return { calls, maker: new FollowupMaker({ makeFollowup: async (id, level) => (calls.push([id, level]), reply()) }) };
};

describe("make", () => {
  test("opens the lesson that was made, asking once", async () => {
    const { calls, maker: made } = maker(async () => ({ lesson_id: "NEW", run_id: "R" }));

    expect(await made.make("PARENT", "foundation")).toEqual({ kind: "open", lessonId: "NEW" });
    expect(calls).toEqual([["PARENT", "foundation"]]);
  });

  test("a lesson that already exists is opened, not reported as a failure", async () => {
    const { maker: made } = maker(() => Promise.reject(new ApiError(409, "already_exists", "x", {}, { lesson_id: "OLD" })));

    expect(await made.make("PARENT", "advanced")).toEqual({ kind: "open", lessonId: "OLD" });
  });

  test("a 409 that is not 'already exists', or names no lesson, is a failure", async () => {
    const wrong = maker(() => Promise.reject(new ApiError(409, "wrong_stage", "x")));
    const nameless = maker(() => Promise.reject(new ApiError(409, "already_exists", "x", {}, {})));
    const odd = maker(() => Promise.reject(new ApiError(409, "already_exists", "x", {}, { lesson_id: 7 })));

    expect((await wrong.maker.make("P", "foundation")).kind).toBe("failed");
    expect((await nameless.maker.make("P", "foundation")).kind).toBe("failed");
    expect((await odd.maker.make("P", "foundation")).kind).toBe("failed");
  });
});

describe("the words for a failure", () => {
  test.each([
    [new ApiError(403, "out_of_credits", "You have used all your lessons for today."), "You have used all your lessons for today."],
    [new ApiError(429, "throttled", "x"), "You've started a lot of lessons just now. Please wait a little while and try again."],
    [new ApiError(503, "llm_not_configured", "x"), "Lesson building is switched off right now. Please try again later."],
    [new ApiError(409, "wrong_stage", "x"), "That lesson isn't ready yet. Try again in a moment."],
    [new ApiError(500, "error", "x"), "We couldn't make that lesson. Please try again."],
    [new Error("boom"), "We couldn't make that lesson. Please try again."],
    [undefined, "We couldn't make that lesson. Please try again."],
  ])("%p", (error, words) => {
    expect(FollowupMaker.message(error)).toBe(words);
  });

  test("a failure carries its words", async () => {
    const { maker: made } = maker(() => Promise.reject(new ApiError(429, "throttled", "x")));

    expect(await made.make("P", "foundation")).toEqual({
      kind: "failed", message: "You've started a lot of lessons just now. Please wait a little while and try again.",
    });
  });

  test("no message names a status code or the machinery", () => {
    for (const error of [new ApiError(429, "t", "x"), new ApiError(503, "llm_not_configured", "x"), new ApiError(500, "e", "x")]) {
      expect(FollowupMaker.message(error)).not.toMatch(/\b[45]\d\d\b|queue|llm|model|celery|redis/i);
    }
  });
});
