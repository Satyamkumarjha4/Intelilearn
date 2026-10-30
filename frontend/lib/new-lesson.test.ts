/**
 * Unit under test: `NewLesson`, the rules of the "What do you want to learn?" form.
 *
 * Why: the first thing a learner does is type a topic. A button that enables at one letter, a counter that disagrees
 * with the limit, or an error that says "503" or "queue" instead of what to do next turns the start of the journey into
 * a dead end.
 *
 * Use cases:
 * - the quick check can start from two characters (spaces do not count), and not while a start is under way
 * - rating yourself needs a pick as well: none, or a value off the scale, cannot start; the rating does not matter to a
 *   quick check
 * - there are two ways to say where you are, each with a label and a line, and each its own intro, steps and button words
 * - the request carries the trimmed topic, and the stars (not the halves) only for a rating
 * - the counter reads "n / 200" and is capped at the limit
 * - clicking an example fills the topic, replacing what was there
 * - each way the API can refuse is explained in plain words, with what to do; a validation message from the API is kept;
 *   a refused action says its own words; a rating the API did not take says to pick the stars
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { NewLesson } from "./new-lesson";

describe("canStart", () => {
  test.each([
    ["", false], ["a", false], ["  a  ", false], ["ab", true], ["  ab ", true], ["Binary search", true],
  ])("%j is %s", (topic, can) => {
    expect(NewLesson.canStart(topic, false)).toBe(can);
  });

  test("not while a start is under way", () => {
    expect(NewLesson.canStart("Binary search", true)).toBe(false);
  });
});

describe("rating yourself", () => {
  test.each([[1, true], [5, true], [10, true], [null, false], [0, false], [11, false], [2.5, false]])("a rating of %p can start: %s", (rating, can) => {
    expect(NewLesson.canStart("Binary search", false, "self_rating", rating)).toBe(can);
  });

  test("a topic that is too short, or a start under way, still stops it", () => {
    expect(NewLesson.canStart("a", false, "self_rating", 5)).toBe(false);
    expect(NewLesson.canStart("Binary search", true, "self_rating", 5)).toBe(false);
  });

  test("a quick check ignores the rating", () => {
    expect(NewLesson.canStart("Binary search", false, "diagnostic", null)).toBe(true);
    expect(NewLesson.canStart("Binary search", false, "diagnostic", 5)).toBe(true);
  });
});

describe("the two ways in", () => {
  test("a quick check and a self-rating, each with a label and a line", () => {
    expect(NewLesson.ENTRIES.map((e) => e.id)).toEqual(["diagnostic", "self_rating"]);
    expect(NewLesson.ENTRIES.map((e) => e.label)).toEqual(["Take a quick check", "Rate yourself"]);
    expect(NewLesson.ENTRIES.every((e) => e.hint.trim().length > 0)).toBe(true);
  });

  test("each has its own intro, steps and button, and a start under way says so", () => {
    expect(NewLesson.intro("diagnostic")).toContain("quick check");
    expect(NewLesson.intro("self_rating")).toContain("no quiz first");
    expect(NewLesson.steps("diagnostic")).toEqual(["Quick check", "Your starting point", "Your lesson"]);
    expect(NewLesson.steps("self_rating")).toEqual(["Your rating", "Your lesson"]);
    expect(NewLesson.buttonLabel("diagnostic", false)).toBe("Start my quick check");
    expect(NewLesson.buttonLabel("self_rating", false)).toBe("Start my lesson");
    expect(NewLesson.buttonLabel("self_rating", true)).toBe("Starting…");
  });

  test("the request trims the topic and sends stars, not halves, only for a rating", () => {
    expect(NewLesson.request("  Binary search ", "note", "diagnostic", 7)).toEqual({ topic: "Binary search", context: "note", options: {} });
    expect(NewLesson.request("Binary search", "", "self_rating", 7)).toEqual({ topic: "Binary search", context: "", options: { selfRating: 3.5 } });
    expect(NewLesson.request("Binary search", "", "self_rating", null).options).toEqual({});
  });
});

test("the counter reads n / 200 and stops at the limit", () => {
  expect(NewLesson.counter("abc")).toBe("3 / 200");
  expect(NewLesson.counter("x".repeat(250))).toBe("200 / 200");
  expect(NewLesson.counter("")).toBe("0 / 200");
});

test("examples are short, different topics", () => {
  expect(NewLesson.EXAMPLES.length).toBeGreaterThanOrEqual(4);
  expect(new Set(NewLesson.EXAMPLES).size).toBe(NewLesson.EXAMPLES.length);
  expect(NewLesson.EXAMPLES.every((topic) => topic.length >= 2 && topic.length <= NewLesson.TOPIC_MAX)).toBe(true);
});

describe("error messages", () => {
  const message = (status: number, code: string, detail = "x", fields = {}) => NewLesson.errorMessage(new ApiError(status, code, detail, fields));

  test("lesson building switched off", () => {
    expect(message(503, "llm_not_configured")).toContain("switched off");
  });

  test("the helper is unreachable", () => {
    expect(message(503, "queue_unavailable")).toContain("Nothing was lost");
  });

  test("too many lessons", () => {
    expect(message(429, "throttled")).toContain("a little while");
  });

  test("a validation message is kept", () => {
    expect(message(400, "invalid", "Please correct the highlighted fields.", { topic: ["Ensure this field has at least 2 characters."] })).toBe(
      "Ensure this field has at least 2 characters.",
    );
  });

  test("a refused action says its own words", () => {
    expect(message(403, "out_of_credits", "You have used all your lessons for today.")).toBe("You have used all your lessons for today.");
  });

  test("a rating the API did not take says to pick the stars", () => {
    expect(message(400, "invalid", "x", { self_rating: ["Stars go in steps of half a star."] })).toContain("Pick the stars");
  });

  test("anything else says we couldn't start it", () => {
    expect(message(500, "error")).toContain("couldn't start");
    expect(NewLesson.errorMessage(new Error("boom"))).toContain("couldn't start");
    expect(NewLesson.errorMessage(undefined)).toContain("couldn't start");
  });

  test("no message names a status code or the machinery", () => {
    for (const text of [message(503, "llm_not_configured"), message(503, "queue_unavailable"), message(429, "throttled"), message(500, "error")]) {
      expect(text).not.toMatch(/\b5\d\d\b|\b429\b|queue|llm|model|celery|redis/i);
    }
  });
});
