/**
 * Unit under test: `QuizzesApi`, the typed calls to the quick quiz endpoints.
 *
 * Why: a wrong path or body shape fails only at runtime in the browser, and the paths have no trailing slash (the Next
 * proxy depends on it). The attempt screens are shared with the lesson test, so the quiz must also read like a lesson's
 * `GET /test` for them.
 *
 * Use cases:
 * - asks which kinds of question suit a topic
 * - makes a quiz with the request as given, lists with a cursor when there is one, reads and deletes a quiz
 * - reads the calibration question and answers it (an "I don't know" is a null answer)
 * - takes the quiz again, lists the attempts, reads one, saves an answer, submits (with or without the last card),
 *   grades a failed one again
 * - makes a lesson from a result, and cancels a run
 * - reads the quiz as the test screens do: the open attempt's questions and saved answers, an attempt that is being
 *   prepared with no questions yet, and nothing when none is open
 */
import { describe, expect, test } from "bun:test";

import type { ApiClient, RequestOptions } from "./api";
import { QuizzesApi } from "./quizzes-api";
import type { QuizAttempt, QuizDetail } from "./types";

function fakeClient(replies: Record<string, unknown> = {}) {
  const calls: { path: string; options?: RequestOptions }[] = [];
  const client = {
    request: async (path: string, options?: RequestOptions) => {
      calls.push({ path, options });
      return replies[path];
    },
  } as unknown as ApiClient;
  return { api: new QuizzesApi(client), calls };
}

describe("QuizzesApi", () => {
  test("asks which kinds suit a topic", async () => {
    const { api, calls } = fakeClient();
    await api.topicTraits("Algebra");
    expect(calls[0]).toEqual({ path: "/quick-quizzes/topic-traits", options: { method: "POST", body: { topic: "Algebra" } } });
  });

  test("makes a quiz with the request as given", async () => {
    const { api, calls } = fakeClient();
    const request = {
      source: { type: "topic" as const, topic: "Algebra" },
      num_questions: 10,
      types: ["mcq" as const],
      level: { mode: "self_rating" as const, rating: 3 },
    };
    await api.create(request);
    expect(calls[0]).toEqual({ path: "/quick-quizzes", options: { method: "POST", body: request } });
  });

  test("lists with a cursor only when there is one, and reads and deletes a quiz", async () => {
    const { api, calls } = fakeClient();
    await api.list();
    await api.list("a b");
    await api.get("q1");
    await api.remove("q1");
    expect(calls.map((c) => [c.path, c.options?.method])).toEqual([
      ["/quick-quizzes", undefined],
      ["/quick-quizzes?cursor=a%20b", undefined],
      ["/quick-quizzes/q1", undefined],
      ["/quick-quizzes/q1", "DELETE"],
    ]);
  });

  test("reads the calibration question and answers it, with null for I don't know", async () => {
    const { api, calls } = fakeClient();
    await api.calibration("q1");
    await api.answerCalibration("q1", "q5", 2);
    await api.answerCalibration("q1", "q7", null);
    expect(calls.map((c) => [c.path, c.options?.body])).toEqual([
      ["/quick-quizzes/q1/calibration", undefined],
      ["/quick-quizzes/q1/calibration/answer", { question_id: "q5", answer: 2 }],
      ["/quick-quizzes/q1/calibration/answer", { question_id: "q7", answer: null }],
    ]);
  });

  test("takes the quiz again, lists and reads attempts, saves an answer and submits", async () => {
    const { api, calls } = fakeClient();
    await api.startAttempt("q1");
    await api.attempts("q1");
    await api.attempt("q1", "a1");
    await api.saveAnswer("q1", "a1", "t1", [0, 2]);
    await api.submitAttempt("q1", "a1");
    await api.submitAttempt("q1", "a1", { t3: "x" });
    await api.regradeAttempt("q1", "a1");
    expect(calls.map((c) => [c.options?.method ?? "GET", c.path, c.options?.body])).toEqual([
      ["POST", "/quick-quizzes/q1/attempts", undefined],
      ["GET", "/quick-quizzes/q1/attempts", undefined],
      ["GET", "/quick-quizzes/q1/attempts/a1", undefined],
      ["PUT", "/quick-quizzes/q1/attempts/a1/answers/t1", { answer: [0, 2] }],
      ["POST", "/quick-quizzes/q1/attempts/a1/submit", {}],
      ["POST", "/quick-quizzes/q1/attempts/a1/submit", { answers: { t3: "x" } }],
      ["POST", "/quick-quizzes/q1/attempts/a1/regrade", undefined],
    ]);
  });

  test("makes a lesson from a result and cancels a run", async () => {
    const { api, calls } = fakeClient();
    await api.createLesson("q1", "a1");
    await api.cancelRun("r1");
    expect(calls.map((c) => [c.path, c.options?.body])).toEqual([
      ["/quick-quizzes/q1/create-lesson", { attempt_id: "a1" }],
      ["/runs/r1/cancel", undefined],
    ]);
  });
});

describe("the quiz read as a test", () => {
  const detail = (open: QuizDetail["open_attempt"], attempts = [1]) =>
    ({ open_attempt: open, attempts: attempts.map((attempt_no) => ({ attempt_no })) }) as unknown as QuizDetail;
  const attempt = (status: QuizAttempt["status"]) =>
    ({
      id: "a2", attempt_no: 2, status, answers: { t1: 1 }, total_marks: 5, started_at: "s", submitted_at: null,
      questions: status === "in_progress" ? [{ id: "t1" }, { id: "t2" }] : [],
    }) as unknown as QuizAttempt;

  test("an attempt in progress has its questions and its saved answers", async () => {
    const open = { id: "a2", attempt_no: 2, status: "in_progress" as const };
    const { api } = fakeClient({ "/quick-quizzes/q1": detail(open, [1, 2]), "/quick-quizzes/q1/attempts/a2": attempt("in_progress") });

    const test = await api.test("q1");

    expect(test.questions.map((q) => q.id)).toEqual(["t1", "t2"]);
    expect(test.answers).toEqual({ t1: 1 });
    expect(test.attempt).toEqual({ id: "a2", attempt_no: 2, status: "in_progress", started_at: "s", submitted_at: null });
    expect(test.next_attempt_no).toBe(3);
  });

  test("an attempt that is still being prepared has no questions yet", async () => {
    const open = { id: "a2", attempt_no: 2, status: "generating" as const };
    const { api } = fakeClient({ "/quick-quizzes/q1": detail(open), "/quick-quizzes/q1/attempts/a2": attempt("generating") });

    const test = await api.test("q1");

    expect(test.questions).toEqual([]);
    expect(test.attempt?.status).toBe("generating");
  });

  test("a quiz with nothing open has no attempt and asks nothing more", async () => {
    const { api, calls } = fakeClient({ "/quick-quizzes/q1": detail(null, [1, 2]) });

    const test = await api.test("q1");

    expect(test).toMatchObject({ questions: [], attempt: null, answers: {}, next_attempt_no: 3, total_marks: 0 });
    expect(calls).toHaveLength(1);
  });
});
