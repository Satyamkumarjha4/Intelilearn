/**
 * Unit under test: `LevelChoice`, how the quiz wizard lets a learner say where they are.
 *
 * Why: the level decides how hard every question is. The wizard starts on the learner's test scores when every lesson
 * has one (so a learner who did well is not asked easy questions) and on their own rating otherwise, but any way of
 * finding the level can be picked: it is the learner's call. Scores belong to lessons only, and a rating is not a
 * choice until the stars are picked.
 *
 * Use cases:
 * - offers scores only for a quiz made from lessons, and the rating and the warm-up always
 * - starts on the scores when every lesson picked has a graded test, else on the rating
 * - says why scores cannot be used (no lessons, or a lesson without a test) and nothing about the other modes
 * - a rating is complete only with its stars, and the other modes always
 * - sends the stars as the API takes them (0.5 to 5) for a rating and just the mode otherwise
 * - names each mode
 */
import { describe, expect, test } from "bun:test";

import { LevelChoice } from "./level-choice";

describe("which modes are offered", () => {
  test("scores only for lessons", () => {
    expect(LevelChoice.options("topic").map((o) => o.id)).toEqual(["self_rating", "calibration"]);
    expect(LevelChoice.options("lessons").map((o) => o.id)).toEqual(["existing_score", "self_rating", "calibration"]);
  });
});

describe("where the wizard starts", () => {
  test.each([
    ["lessons", [true, true], "existing_score"],
    ["lessons", [true, false], "self_rating"],
    ["lessons", [], "self_rating"],
    ["topic", [], "self_rating"],
    ["topic", [true], "self_rating"],
  ] as const)("%s with scores %p starts on %s", (source, scored, mode) => {
    expect(LevelChoice.defaultMode(source, scored)).toBe(mode);
  });
});

describe("why a mode is not available", () => {
  test("scores need lessons that have all had a test", () => {
    expect(LevelChoice.unavailable("existing_score", "topic", [])).toBe("Scores belong to lessons.");
    expect(LevelChoice.unavailable("existing_score", "lessons", [true, false])).toBe("Some of these lessons haven't had a test yet.");
    expect(LevelChoice.unavailable("existing_score", "lessons", [true])).toBeNull();
  });

  test("the other modes are always available", () => {
    expect(LevelChoice.unavailable("self_rating", "topic", [])).toBeNull();
    expect(LevelChoice.unavailable("calibration", "lessons", [false])).toBeNull();
  });
});

describe("what is sent", () => {
  test("a rating needs its stars and is sent as stars", () => {
    expect(LevelChoice.ready("self_rating", null)).toBe(false);
    expect(LevelChoice.ready("self_rating", 6)).toBe(true);
    expect(LevelChoice.request("self_rating", null)).toBeNull();
    expect(LevelChoice.request("self_rating", 7)).toEqual({ mode: "self_rating", rating: 3.5 });
  });

  test("the other modes are just the mode", () => {
    expect(LevelChoice.request("calibration", null)).toEqual({ mode: "calibration" });
    expect(LevelChoice.request("existing_score", 4)).toEqual({ mode: "existing_score" });
    expect(LevelChoice.ready("calibration", null)).toBe(true);
  });

  test("every mode has a name", () => {
    expect(LevelChoice.label("calibration")).toBe("A quick warm-up");
    expect(LevelChoice.label("existing_score")).toBe("Use my test scores");
  });
});
