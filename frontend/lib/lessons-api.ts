import { apiClient, type ApiClient } from "@/lib/api";
import type {
  Answer,
  LessonDetail,
  LessonDocument,
  LessonSummary,
  LessonVersion,
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
  TestSubmissionCreated,
} from "@/lib/types";

export type LessonQuery = { q?: string; stage?: Stage | ""; cursor?: string | null; pageSize?: number };

/** The lessons endpoints (docs/api.md), typed. */
export class LessonsApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  list(query: LessonQuery = {}): Promise<Page<LessonSummary>> {
    const params = new URLSearchParams();
    if (query.q?.trim()) params.set("q", query.q.trim());
    if (query.stage) params.set("stage", query.stage);
    if (query.cursor) params.set("cursor", query.cursor);
    if (query.pageSize) params.set("page_size", String(query.pageSize));
    const text = params.toString();
    return this.client.request(`/lessons${text ? `?${text}` : ""}`);
  }

  create(topic: string, userContext: string): Promise<{ lesson_id: string; run_id: string }> {
    return this.client.request("/lessons", { method: "POST", body: { topic, user_context: userContext } });
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

  choose(id: string, kind: MaterialKind): Promise<{ run_id: string }> {
    return this.client.request(`/lessons/${id}/choice`, { method: "POST", body: { kind } });
  }

  requestMaterial(id: string, kind: MaterialKind): Promise<{ run_id: string }> {
    return this.client.request(`/lessons/${id}/materials`, { method: "POST", body: { kind } });
  }

  material<T>(id: string, kind: MaterialKind, reveal: string[] = []): Promise<StudyMaterial<T>> {
    const query = reveal.length ? `?${reveal.map((q) => `reveal=${encodeURIComponent(q)}`).join("&")}` : "";
    return this.client.request(`/lessons/${id}/materials/${kind}${query}`);
  }

  gradePractice(id: string, answers: Record<string, number | string>): Promise<PracticeGrade> {
    return this.client.request(`/lessons/${id}/materials/practice_sheet/grade`, { method: "POST", body: { answers } });
  }

  document(id: string): Promise<LessonDocument> {
    return this.client.request(`/lessons/${id}/document`);
  }

  requestRepair(id: string, error: RepairError, codeVersion: number): Promise<{ run_id: string }> {
    return this.client.request(`/lessons/${id}/repair`, { method: "POST", body: { error, code_version: codeVersion } });
  }

  submitTest(id: string, answers: Record<string, unknown>): Promise<TestSubmissionCreated> {
    return this.client.request(`/lessons/${id}/test/submissions`, { method: "POST", body: { answers } });
  }

  submission(id: string, submissionId: string): Promise<TestSubmission> {
    return this.client.request(`/lessons/${id}/test/submissions/${submissionId}`);
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
