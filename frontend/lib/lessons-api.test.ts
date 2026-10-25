/**
 * Unit under test: `LessonsApi`, the typed calls to the lessons endpoints.
 *
 * Why: a wrong path or body shape fails only at runtime in the browser. The paths have no trailing slash (the Next
 * proxy depends on it), and the cursor must be taken from the backend's absolute `next` link.
 *
 * Use cases:
 * - lists with only the query parameters that were given
 * - creates a lesson with the topic and the learner's context
 * - reads, deletes and retries a lesson
 * - reads a quiz and submits answers to its attempt endpoint
 * - reads the review and cancels a run
 * - chooses a sheet, asks for another, reads one (with revealed solutions) and grades practice answers
 * - reads the lesson document, reports a crash for repair, lists versions and restores one
 * - submits the lesson test and reads a submission
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

    expect(calls.map((c) => c.path)).toEqual([
      "/lessons",
      "/lessons?q=binary&stage=ready&cursor=abc&page_size=5",
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

    await api.choose("l1", "cheat_sheet");
    await api.requestMaterial("l1", "revision_sheet");
    await api.material("l1", "cheat_sheet");
    await api.material("l1", "practice_sheet", ["t1", "t 2"]);
    await api.gradePractice("l1", { t1: 2, t2: "4" });

    expect(calls).toEqual([
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

  test("submits the lesson test and reads a submission", async () => {
    const { api, calls } = fakeClient();

    await api.submitTest("L1", { t1: 2, t2: "text" });
    await api.submission("L1", "S1");

    expect(calls.map((c) => [c.path, c.options?.method])).toEqual([
      ["/lessons/L1/test/submissions", "POST"],
      ["/lessons/L1/test/submissions/S1", undefined],
    ]);
    expect(calls[0].options?.body).toEqual({ answers: { t1: 2, t2: "text" } });
  });

  test("extracts the cursor from a next link", () => {
    expect(LessonsApi.cursorOf("http://backend:8000/api/lessons?cursor=cD0yMDI2&page_size=2")).toBe("cD0yMDI2");
    expect(LessonsApi.cursorOf(null)).toBeNull();
    expect(LessonsApi.cursorOf("http://x/api/lessons")).toBeNull();
  });
});
