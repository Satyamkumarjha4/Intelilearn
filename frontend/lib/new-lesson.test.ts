/**
 * Unit under test: `NewLesson`, the rules of the "What do you want to learn?" form.
 *
 * Why: the first thing a learner does is type a topic. A button that enables at one letter, a counter that disagrees
 * with the limit, or an error that says "503" or "queue" instead of what to do next turns the start of the journey into
 * a dead end.
 *
 * Use cases:
 * - the quick check can start from two characters (spaces do not count), and not while a start is under way
 * - the counter reads "n / 200" and is capped at the limit
 * - clicking an example fills the topic, replacing what was there
 * - each way the API can refuse is explained in plain words, with what to do; a validation message from the API is kept
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
