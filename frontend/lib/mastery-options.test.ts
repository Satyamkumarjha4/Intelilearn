/**
 * Unit under test: `MasteryOptions`, the two cards a learner sees after a perfect quick check, and the words around them.
 *
 * Why: this is the one place a learner who did everything right decides what happens next. The two options must read
 * exactly as agreed, and the Expert lesson must be what is picked unless they say otherwise.
 *
 * Use cases:
 * - there are two options, the Expert lesson first, with exactly the agreed titles
 * - each has a line, two bullets and a time, and no word the learner should not see (a model, a run, a node)
 * - an option is found by its pick; the Expert lesson is the default
 * - the button follows the card picked and says so while starting
 * - a refusal is said in its own words, a choice made twice says to reload, and anything else says to try again
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { MasteryOptions } from "./mastery-options";

describe("the options", () => {
  test("the Expert lesson, then the two sheets, with exactly the agreed titles", () => {
    expect(MasteryOptions.all().map((o) => o.pick)).toEqual(["lesson", "sheets"]);
    expect(MasteryOptions.all().map((o) => o.title)).toEqual(["Continue with an Expert lesson", "Cheat sheet + revision sheet only"]);
  });

  test("each has a line, two bullets and a time, in plain words", () => {
    for (const option of MasteryOptions.all()) {
      expect(option.text.trim().length).toBeGreaterThan(0);
      expect(option.bullets.every((bullet) => bullet.trim().length > 0)).toBe(true);
      expect(option.time.trim().length).toBeGreaterThan(0);
      expect(JSON.stringify(option)).not.toMatch(/\b(node|run|graph|pipeline|stage|llm|model)\b/i);
    }
  });

  test("an option is found by its pick, and the Expert lesson is the default", () => {
    expect(MasteryOptions.of("sheets").title).toContain("Cheat sheet");
    expect(MasteryOptions.DEFAULT).toBe("lesson");
  });
});

describe("the button", () => {
  test("follows the card picked, and says so while starting", () => {
    expect(MasteryOptions.buttonLabel("lesson", false)).toBe("Start my Expert lesson");
    expect(MasteryOptions.buttonLabel("sheets", false)).toBe("Make my two sheets");
    expect(MasteryOptions.buttonLabel("lesson", true)).toBe("Starting…");
  });
});

describe("when the pick does not go through", () => {
  test("a refusal says its own words", () => {
    expect(MasteryOptions.errorMessage(new ApiError(403, "out_of_credits", "You have used all your lessons for today."))).toBe(
      "You have used all your lessons for today.",
    );
  });

  test("a choice made twice says to reload", () => {
    expect(MasteryOptions.errorMessage(new ApiError(409, "wrong_stage", "x"))).toContain("already made");
  });

  test.each([new ApiError(500, "error", "x"), new Error("boom"), undefined])("anything else says to try again (%p)", (error) => {
    expect(MasteryOptions.errorMessage(error)).toContain("try again");
  });
});
