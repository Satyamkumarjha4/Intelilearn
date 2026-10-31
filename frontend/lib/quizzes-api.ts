import { apiClient, type ApiClient } from "@/lib/api";
import type {
  AnswerSaved,
  AttemptHistory,
  AttemptStarted,
  Calibration,
  LearnerTest,
  Page,
  QuizAttempt,
  QuizCreateRequest,
  QuizDetail,
  QuizSubmitted,
  QuizSummary,
  TopicTraits,
} from "@/lib/types";

/** The quick quiz endpoints (docs/reference/api.md), typed. */
export class QuizzesApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  /** Which kinds of question suit a topic. The server never fails this: `source: "fallback"` offers every kind. */
  topicTraits(topic: string): Promise<TopicTraits> {
    return this.client.request("/quick-quizzes/topic-traits", { method: "POST", body: { topic } });
  }

  create(request: QuizCreateRequest): Promise<{ quiz_id: string; run_id: string }> {
    return this.client.request("/quick-quizzes", { method: "POST", body: request });
  }

  list(cursor?: string | null): Promise<Page<QuizSummary>> {
    return this.client.request(`/quick-quizzes${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`);
  }

  get(id: string): Promise<QuizDetail> {
    return this.client.request(`/quick-quizzes/${id}`);
  }

  remove(id: string): Promise<void> {
    return this.client.request(`/quick-quizzes/${id}`, { method: "DELETE" });
  }

  calibration(id: string): Promise<Calibration> {
    return this.client.request(`/quick-quizzes/${id}/calibration`);
  }

  /** Answers the question the walk is on; `null` is "I don't know". The server decides what comes next. */
  answerCalibration(id: string, questionId: string, answer: number | null): Promise<Calibration> {
    return this.client.request(`/quick-quizzes/${id}/calibration/answer`, {
      method: "POST",
      body: { question_id: questionId, answer },
    });
  }

  /** Takes the quiz again with new questions, or returns the attempt that is open. A retake is `generating` first. */
  startAttempt(id: string): Promise<AttemptStarted> {
    return this.client.request(`/quick-quizzes/${id}/attempts`, { method: "POST" });
  }

  attempts(id: string): Promise<AttemptHistory> {
    return this.client.request(`/quick-quizzes/${id}/attempts`);
  }

  /** One attempt: its questions and saved answers while it is open, its card and advice once it is over. */
  attempt(id: string, attemptId: string): Promise<QuizAttempt> {
    return this.client.request(`/quick-quizzes/${id}/attempts/${attemptId}`);
  }

  /** Saves one answer and locks the question (409 `locked` afterwards). `null` leaves it blank. */
  saveAnswer(id: string, attemptId: string, questionId: string, answer: unknown): Promise<AnswerSaved> {
    return this.client.request(`/quick-quizzes/${id}/attempts/${attemptId}/answers/${questionId}`, {
      method: "PUT",
      body: { answer },
    });
  }

  submitAttempt(id: string, attemptId: string, answers?: Record<string, unknown>): Promise<QuizSubmitted> {
    return this.client.request(`/quick-quizzes/${id}/attempts/${attemptId}/submit`, {
      method: "POST",
      body: answers === undefined ? {} : { answers },
    });
  }

  regradeAttempt(id: string, attemptId: string): Promise<{ run_id: string }> {
    return this.client.request(`/quick-quizzes/${id}/attempts/${attemptId}/regrade`, { method: "POST" });
  }

  /** "Create a lesson for this": for a quiz about a topic, from one of its graded attempts. */
  createLesson(id: string, attemptId: string): Promise<{ lesson_id: string; run_id: string }> {
    return this.client.request(`/quick-quizzes/${id}/create-lesson`, { method: "POST", body: { attempt_id: attemptId } });
  }

  cancelRun(runId: string): Promise<void> {
    return this.client.request(`/runs/${runId}/cancel`, { method: "POST" });
  }

  /**
   * The quiz as the attempt screens read a lesson's test: the open attempt's questions and saved answers, or none. It
   * lets the one runner and the one "getting your questions ready" wait serve both (`AttemptPreparation` asks for it).
   */
  async test(id: string): Promise<LearnerTest> {
    const quiz = await this.get(id);
    const open = quiz.open_attempt;
    const attempt = open ? await this.attempt(id, open.id) : null;
    return {
      questions: attempt?.status === "in_progress" ? attempt.questions : [],
      total_marks: attempt?.total_marks ?? 0,
      attempt: open && attempt
        ? { id: open.id, attempt_no: open.attempt_no, status: attempt.status, started_at: attempt.started_at, submitted_at: attempt.submitted_at }
        : null,
      answers: attempt?.answers ?? {},
      next_attempt_no: (quiz.attempts.at(-1)?.attempt_no ?? 0) + 1,
      submission: null,
    };
  }
}

export const quizzesApi = new QuizzesApi();
