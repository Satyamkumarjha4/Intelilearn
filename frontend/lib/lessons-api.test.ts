/**
 * Unit under test: `LessonsApi`, the typed calls to the lessons endpoints.
 *
 * Why: a wrong path or body shape fails only at runtime in the browser. The paths have no trailing slash (the Next
 * proxy depends on it), and the cursor must be taken from the backend's absolute `next` link.
 *
 * Use cases:
 * - lists with only the query parameters that were given, and several stages as one comma-separated parameter
 * - creates a lesson with the topic and the learner's context, with their rating when they rated themselves, and with the
 *   attempt and topic of a test result when the lesson was recommended by one
 * - reads, deletes and retries a lesson
 * - reads a quiz and submits answers to its attempt endpoint
 * - reads the review and cancels a run
 * - chooses the Expert lesson or the sheets (or, for a lesson already waiting at the old choice, one sheet kind), asks
 *   for another sheet, reads one (with revealed solutions) and grades practice answers
 * - reads the lesson document, reports a crash for repair, lists versions and restores one
 * - reads the test to take, starts an attempt, saves an answer, submits, reads the attempts and one attempt, and grades a
 *   failed one again
 * - extracts the cursor from a `next` link, and handles no link
 */
import { describe, expect, test } from "bun:test";

import type { ApiClient, RequestOptions } from "./api";
import { LessonsApi } from "./lessons-api";

function fakeClient() {
  const calls: { path: string; options?: RequestOptions }[] = [];
  const client = {
    request: async (path: string, options?: RequestOptions) => {
      calls.push({ path, options });
      return undefined;
    },
  } as unknown as ApiClient;
  return { api: new LessonsApi(client), calls };
}

describe("LessonsApi", () => {
  test("lists with only the query parameters that were given", async () => {
    const { api, calls } = fakeClient();

    await api.list();
    await api.list({ q: " binary ", stage: "ready", cursor: "abc", pageSize: 5 });
    await api.list({ q: "  ", stage: "" });
    await api.list({ stage: ["awaiting_diagnostic", "awaiting_choice"] });
    await api.list({ stage: [] });

    expect(calls.map((c) => c.path)).toEqual([
      "/lessons",
      "/lessons?q=binary&stage=ready&cursor=abc&page_size=5",
      "/lessons",
      "/lessons?stage=awaiting_diagnostic%2Cawaiting_choice",
      "/lessons",
    ]);
  });

  test("creates a lesson with the topic and context", async () => {
    const { api, calls } = fakeClient();

    await api.create("Binary search", "for my exam");

    expect(calls[0]).toEqual({
      path: "/lessons",
      options: { method: "POST", body: { topic: "Binary search", user_context: "for my exam" } },
    });
  });

  test("a rating starts a lesson with no quick check", async () => {
    const { api, calls } = fakeClient();

    await api.create("Binary search", "", { selfRating: 3.5 });

    expect(calls[0].options).toEqual({
      method: "POST",
      body: { topic: "Binary search", user_context: "", entry: "self_rating", self_rating: 3.5 },
    });
  });

  test("a topic a test result listed names the attempt and the topic", async () => {
    const { api, calls } = fakeClient();

    await api.create("Off by one", "", { recommendedFrom: { attemptId: "a1", topic: "Off by one" } });

    expect(calls[0].options).toEqual({
      method: "POST",
      body: {
        topic: "Off by one", user_context: "", origin: "recommendation",
        recommended_from: { attempt_id: "a1", topic: "Off by one" },
      },
    });
  });

  test("reads, deletes and retries a lesson", async () => {
    const { api, calls } = fakeClient();

    await api.get("l1");
    await api.remove("l1");
    await api.retry("l1");

    expect(calls).toEqual([
      { path: "/lessons/l1", options: undefined },
      { path: "/lessons/l1", options: { method: "DELETE" } },
      { path: "/lessons/l1/retry", options: { method: "POST" } },
    ]);
  });

  test("reads a quiz and submits answers to its attempt endpoint", async () => {
    const { api, calls } = fakeClient();

    await api.quiz("l1", "prerequisite");
    await api.submitQuiz("l1", "diagnostic", { q1: 2, q2: "dont_know" });

    expect(calls[0].path).toBe("/lessons/l1/quizzes/prerequisite");
    expect(calls[1]).toEqual({
      path: "/lessons/l1/quizzes/diagnostic/attempt",
      options: { method: "POST", body: { answers: { q1: 2, q2: "dont_know" } } },
    });
  });

  test("reads the review and cancels a run", async () => {
    const { api, calls } = fakeClient();

    await api.review("l1", "diagnostic");
    await api.cancelRun("r1");

    expect(calls.map((c) => c.path)).toEqual(["/lessons/l1/quizzes/diagnostic/review", "/runs/r1/cancel"]);
    expect(calls[1].options).toEqual({ method: "POST" });
  });

  test("chooses a sheet, asks for another, reads one with revealed solutions and grades practice", async () => {
    const { api, calls } = fakeClient();

    await api.choose("l1", "lesson");
    await api.choose("l1", "sheets");
    await api.choose("l1", { kind: "cheat_sheet" });
    await api.requestMaterial("l1", "revision_sheet");
    await api.material("l1", "cheat_sheet");
    await api.material("l1", "practice_sheet", ["t1", "t 2"]);
    await api.gradePractice("l1", { t1: 2, t2: "4" });

    expect(calls).toEqual([
      { path: "/lessons/l1/choice", options: { method: "POST", body: { choice: "lesson" } } },
      { path: "/lessons/l1/choice", options: { method: "POST", body: { choice: "sheets" } } },
      { path: "/lessons/l1/choice", options: { method: "POST", body: { kind: "cheat_sheet" } } },
      { path: "/lessons/l1/materials", options: { method: "POST", body: { kind: "revision_sheet" } } },
      { path: "/lessons/l1/materials/cheat_sheet", options: undefined },
      { path: "/lessons/l1/materials/practice_sheet?reveal=t1&reveal=t%202", options: undefined },
      {
        path: "/lessons/l1/materials/practice_sheet/grade",
        options: { method: "POST", body: { answers: { t1: 2, t2: "4" } } },
      },
    ]);
  });

  test("reads the document, reports a crash for repair, lists versions and restores one", async () => {
    const { api, calls } = fakeClient();

    await api.document("L1");
    await api.requestRepair("L1", { message: "boom", page: "core" }, 3);
    await api.versions("L1");
    await api.restoreVersion("L1", 2);

    expect(calls.map((c) => [c.path, c.options?.method])).toEqual([
      ["/lessons/L1/document", undefined],
      ["/lessons/L1/repair", "POST"],
      ["/lessons/L1/versions", undefined],
      ["/lessons/L1/versions/2/restore", "POST"],
    ]);
    expect(calls[1].options?.body).toEqual({ error: { message: "boom", page: "core" }, code_version: 3 });
  });

  test("reads the test to take, starts an attempt, saves an answer, submits it and reads the attempts", async () => {
    const { api, calls } = fakeClient();

    await api.test("L1");
    await api.startAttempt("L1");
    await api.saveAnswer("L1", "A1", "t1", [0, 2]);
    await api.submitAttempt("L1", "A1", { t2: "text" });
    await api.submitAttempt("L1", "A1");
    await api.attempts("L1");
    await api.attempt("L1", "A1");
    await api.regradeAttempt("L1", "A1");

    expect(calls.map((c) => [c.path, c.options?.method])).toEqual([
      ["/lessons/L1/test", undefined],
      ["/lessons/L1/test/attempts", "POST"],
      ["/lessons/L1/test/attempts/A1/answers/t1", "PUT"],
      ["/lessons/L1/test/attempts/A1/submit", "POST"],
      ["/lessons/L1/test/attempts/A1/submit", "POST"],
      ["/lessons/L1/test/attempts", undefined],
      ["/lessons/L1/test/attempts/A1", undefined],
      ["/lessons/L1/test/attempts/A1/regrade", "POST"],
    ]);
    expect(calls[2].options?.body).toEqual({ answer: [0, 2] });
    expect(calls[3].options?.body).toEqual({ answers: { t2: "text" } });
    expect(calls[4].options?.body).toEqual({});
    expect(calls[7].options?.body).toBeUndefined();
  });

  test("extracts the cursor from a next link", () => {
    expect(LessonsApi.cursorOf("http://backend:8000/api/lessons?cursor=cD0yMDI2&page_size=2")).toBe("cD0yMDI2");
    expect(LessonsApi.cursorOf(null)).toBeNull();
    expect(LessonsApi.cursorOf("http://x/api/lessons")).toBeNull();
  });
});
