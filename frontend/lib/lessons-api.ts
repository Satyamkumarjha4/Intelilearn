import { apiClient, type ApiClient } from "@/lib/api";
import type {
  AnswerSaved,
  AttemptHistory,
  AttemptStarted,
  AttemptSubmitted,
  Answer,
  LearnerTest,
  LessonDetail,
  LessonDocument,
  LessonSummary,
  LessonVersion,
  MasteryPick,
  MaterialKind,
  Page,
  PracticeGrade,
  QuizForLearner,
  QuizKind,
  QuizResultSummary,
  QuizReview,
  RepairError,
  Stage,
  StudyMaterial,
  TestSubmission,
} from "@/lib/types";

/** How a lesson starts beyond the topic: with the learner's own rating, or from a topic a test result listed. */
export type CreateOptions = {
  /** Stars, 0.5 to 5. Present means "rate yourself": there is no quick check. */
  selfRating?: number;
  recommendedFrom?: { attemptId: string; topic: string };
};

export type LessonQuery = { q?: string; stage?: Stage | Stage[] | ""; cursor?: string | null; pageSize?: number };

/** The lessons endpoints (docs/reference/api.md), typed. */
export class LessonsApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  list(query: LessonQuery = {}): Promise<Page<LessonSummary>> {
    const params = new URLSearchParams();
    if (query.q?.trim()) params.set("q", query.q.trim());
    const stages = [query.stage ?? []].flat().filter(Boolean);
    if (stages.length) params.set("stage", stages.join(","));
    if (query.cursor) params.set("cursor", query.cursor);
    if (query.pageSize) params.set("page_size", String(query.pageSize));
    const text = params.toString();
    return this.client.request(`/lessons${text ? `?${text}` : ""}`);
  }

  /**
   * Starts a lesson. A quick check is the default; a rating (in stars, 0.5 to 5) starts the lesson without one. A
   * lesson made from a test result names the attempt and the topic it listed, and the server checks both.
   */
  create(topic: string, userContext: string, options: CreateOptions = {}): Promise<{ lesson_id: string; run_id: string }> {
    const body: Record<string, unknown> = { topic, user_context: userContext };
    if (options.selfRating !== undefined) Object.assign(body, { entry: "self_rating", self_rating: options.selfRating });
    if (options.recommendedFrom) {
      Object.assign(body, {
        origin: "recommendation",
        recommended_from: { attempt_id: options.recommendedFrom.attemptId, topic: options.recommendedFrom.topic },
      });
    }
    return this.client.request("/lessons", { method: "POST", body });
  }

  get(id: string): Promise<LessonDetail> {
    return this.client.request(`/lessons/${id}`);
  }

  remove(id: string): Promise<void> {
    return this.client.request(`/lessons/${id}`, { method: "DELETE" });
  }

  retry(id: string): Promise<{ run_id: string }> {
    return this.client.request(`/lessons/${id}/retry`, { method: "POST" });
  }

  quiz(id: string, kind: QuizKind): Promise<QuizForLearner> {
    return this.client.request(`/lessons/${id}/quizzes/${kind}`);
  }

  submitQuiz(
    id: string,
    kind: QuizKind,
    answers: Record<string, Answer>,
  ): Promise<{ result: QuizResultSummary; run_id: string }> {
    return this.client.request(`/lessons/${id}/quizzes/${kind}/attempt`, { method: "POST", body: { answers } });
  }

  review(id: string, kind: QuizKind): Promise<QuizReview> {
    return this.client.request(`/lessons/${id}/quizzes/${kind}/review`);
  }

  /** The pick after a perfect quick check: `lesson` or `sheets`; a lesson already waiting at the old three-sheet
   *  choice sends the sheet kind it picked instead. */
  choose(id: string, pick: MasteryPick | { kind: MaterialKind }): Promise<{ run_id: string }> {
    const body = typeof pick === "string" ? { choice: pick } : { kind: pick.kind };
    return this.client.request(`/lessons/${id}/choice`, { method: "POST", body });
  }

  requestMaterial(id: string, kind: MaterialKind): Promise<{ run_id: string }> {
    return this.client.request(`/lessons/${id}/materials`, { method: "POST", body: { kind } });
  }

  material<T>(id: string, kind: MaterialKind, reveal: string[] = []): Promise<StudyMaterial<T>> {
    const query = reveal.length ? `?${reveal.map((q) => `reveal=${encodeURIComponent(q)}`).join("&")}` : "";
    return this.client.request(`/lessons/${id}/materials/${kind}${query}`);
  }

  gradePractice(id: string, answers: Record<string, number | number[] | string>): Promise<PracticeGrade> {
    return this.client.request(`/lessons/${id}/materials/practice_sheet/grade`, { method: "POST", body: { answers } });
  }

  document(id: string): Promise<LessonDocument> {
    return this.client.request(`/lessons/${id}/document`);
  }

  requestRepair(id: string, error: RepairError, codeVersion: number): Promise<{ run_id: string }> {
    return this.client.request(`/lessons/${id}/repair`, { method: "POST", body: { error, code_version: codeVersion } });
  }

  /** The test as its own screen: the open attempt's questions and saved answers, or none. It never starts anything. */
  test(id: string): Promise<LearnerTest> {
    return this.client.request(`/lessons/${id}/test`);
  }

  /** Opens the next attempt, or returns the one that is open. The first has its questions; a retake is `generating`. */
  startAttempt(id: string): Promise<AttemptStarted> {
    return this.client.request(`/lessons/${id}/test/attempts`, { method: "POST" });
  }

  /** Saves one answer and locks the question: it cannot change afterwards (409 `locked`). `null` leaves it blank. */
  saveAnswer(id: string, attemptId: string, questionId: string, answer: Answer | number[] | string | null): Promise<AnswerSaved> {
    return this.client.request(`/lessons/${id}/test/attempts/${attemptId}/answers/${questionId}`, { method: "PUT", body: { answer } });
  }

  /** Seals the attempt. `answers` fills questions that are not locked yet (the last card). */
  submitAttempt(id: string, attemptId: string, answers?: Record<string, unknown>): Promise<AttemptSubmitted> {
    return this.client.request(`/lessons/${id}/test/attempts/${attemptId}/submit`, {
      method: "POST",
      body: answers === undefined ? {} : { answers },
    });
  }

  /** Every attempt, oldest first, and the trend of the graded ones. */
  attempts(id: string): Promise<AttemptHistory> {
    return this.client.request(`/lessons/${id}/test/attempts`);
  }

  /** One attempt, read-only, with its card; the latest one has the highest `attempt_no`. */
  attempt(id: string, attemptId: string): Promise<TestSubmission> {
    return this.client.request(`/lessons/${id}/test/attempts/${attemptId}`);
  }

  /** Grades a failed attempt again on the answers it already has (never new ones). */
  regradeAttempt(id: string, attemptId: string): Promise<{ run_id: string }> {
    return this.client.request(`/lessons/${id}/test/attempts/${attemptId}/regrade`, { method: "POST" });
  }

  versions(id: string): Promise<LessonVersion[]> {
    return this.client.request(`/lessons/${id}/versions`);
  }

  restoreVersion(id: string, number: number): Promise<{ code_version: number }> {
    return this.client.request(`/lessons/${id}/versions/${number}/restore`, { method: "POST" });
  }

  cancelRun(runId: string): Promise<void> {
    return this.client.request(`/runs/${runId}/cancel`, { method: "POST" });
  }

  /** The cursor inside a `next` link from a list reply (the link itself points at the backend's own host). */
  static cursorOf(next: string | null): string | null {
    if (!next) return null;
    return new URL(next, "http://placeholder").searchParams.get("cursor");
  }
}

export const lessonsApi = new LessonsApi();
