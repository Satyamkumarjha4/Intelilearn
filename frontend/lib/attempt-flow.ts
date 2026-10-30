import { ApiError } from "@/lib/api";
import type { DeckAnswer } from "@/lib/deck-session";
import type { LessonsApi } from "@/lib/lessons-api";
import type { LearnerTest, TestSubmission } from "@/lib/types";

/** Follows a run to its end: calls `onEnd` once, and returns what stops following. */
export type FollowRun = (runId: string, onEnd: () => void) => () => void;

/** What the server says about an attempt when it is too late or too early for what the learner did. */
export class AttemptErrors {
  /** The answer was already saved: the server's copy stands. */
  static locked(error: unknown): boolean {
    return error instanceof ApiError && error.status === 409 && error.code === "locked";
  }

  /** The attempt is over (submitted in another tab, or twice). */
  static sealed(error: unknown): boolean {
    return error instanceof ApiError && error.status === 409 && error.code === "attempt_sealed";
  }

  /** Words for a refused start or save, for the learner. */
  static message(error: unknown, fallback: string): string {
    if (error instanceof ApiError && error.code === "retake_limit") return "That's enough tries for today. You can try again tomorrow.";
    if (error instanceof ApiError && error.status === 429) return "You're going a bit fast. Wait a moment and try again.";
    return error instanceof ApiError ? error.message : fallback;
  }
}

export type Preparation = { kind: "ready"; test: LearnerTest } | { kind: "failed" };

/**
 * Opens an attempt and waits until it has its questions. The first attempt is ready at once; a retake is written when
 * it is asked for, so this follows the run that writes it. If the run fails or is stopped the server removes the
 * waiting attempt, which is how this knows ("failed": nothing was lost, the learner can try again).
 */
export class AttemptPreparation {
  private stop: (() => void) | null = null;
  private disposed = false;

  constructor(
    private readonly api: Pick<LessonsApi, "startAttempt" | "test">,
    private readonly follow: FollowRun,
    private readonly pause: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  ) {}

  static readonly POLL_MS = 2000;
  static readonly POLLS = 45;

  /** `onPreparing` is called when the questions have to be written first. */
  async run(lessonId: string, onPreparing: () => void): Promise<Preparation> {
    const started = await this.api.startAttempt(lessonId);
    if (started.status === "generating") {
      onPreparing();
      if (started.run_id) await this.untilEnd(started.run_id);
      else await this.poll(lessonId);
    }
    if (this.disposed) return { kind: "failed" };
    const test = await this.api.test(lessonId);
    return test.attempt?.status === "in_progress" ? { kind: "ready", test } : { kind: "failed" };
  }

  /** Stop following (the page was left). */
  dispose(): void {
    this.disposed = true;
    this.stop?.();
    this.stop = null;
  }

  private untilEnd(runId: string): Promise<void> {
    return new Promise<void>((resolve) => {
      if (this.disposed) return resolve();
      this.stop = this.follow(runId, resolve);
    }).finally(() => {
      this.stop = null;
    });
  }

  /** Without a run to follow (a repeated start after the run was gone), ask now and then. */
  private async poll(lessonId: string): Promise<void> {
    for (let n = 0; n < AttemptPreparation.POLLS && !this.disposed; n++) {
      const test = await this.api.test(lessonId);
      if (test.attempt?.status !== "generating") return;
      await this.pause(AttemptPreparation.POLL_MS);
    }
  }
}

export type LockResult = { ok: true } | { ok: false; sealed: boolean; message: string };

/**
 * Saves the answer of the card the learner is leaving, and with it locks that question on the server: forward-only is a
 * rule of the server, so a refresh or another tab cannot go back either. An answer that was saved already (a double
 * click, a resumed attempt) counts as saved.
 */
export class AnswerLocker {
  constructor(private readonly api: Pick<LessonsApi, "saveAnswer">) {}

  async lock(lessonId: string, attemptId: string, questionId: string, answer: DeckAnswer): Promise<LockResult> {
    try {
      await this.api.saveAnswer(lessonId, attemptId, questionId, answer);
      return { ok: true };
    } catch (error) {
      if (AttemptErrors.locked(error)) return { ok: true };
      return { ok: false, sealed: AttemptErrors.sealed(error), message: AttemptErrors.message(error, "We couldn't save your answer. Try again.") };
    }
  }
}

/**
 * Submits the attempt and follows the grading to its end. A lesson attempt has only questions with one right answer, so
 * the reply already is the result; a lesson from before the fixed test may have written answers, which a model marks
 * in a run that is followed here, and the attempt is read again when it ends. An attempt that is already over (a second
 * tab, a double click) is simply read.
 */
export class AttemptSubmitFlow {
  private stop: (() => void) | null = null;
  private disposed = false;

  constructor(
    private readonly api: Pick<LessonsApi, "submitAttempt" | "attempt">,
    private readonly follow: FollowRun,
  ) {}

  /** Resolves with the attempt as it ended (graded, or failed with its reason). `onUpdate` sees every state. */
  async run(lessonId: string, attemptId: string, last: Record<string, unknown>, onUpdate: (attempt: TestSubmission) => void): Promise<TestSubmission> {
    let runId: string | null = null;
    try {
      runId = (await this.api.submitAttempt(lessonId, attemptId, last)).run_id;
    } catch (error) {
      if (!AttemptErrors.sealed(error)) throw error;
    }
    let attempt = await this.api.attempt(lessonId, attemptId);
    if (!this.disposed) onUpdate(attempt);
    if (attempt.status !== "grading" || !runId) return attempt;
    await new Promise<void>((resolve) => {
      if (this.disposed) return resolve();
      this.stop = this.follow(runId!, resolve);
    });
    this.stop = null;
    attempt = await this.api.attempt(lessonId, attemptId);
    if (!this.disposed) onUpdate(attempt);
    return attempt;
  }

  /** Stop following (the page was left). Nothing more is reported. */
  dispose(): void {
    this.disposed = true;
    this.stop?.();
    this.stop = null;
  }
}
