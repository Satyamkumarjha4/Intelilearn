import type { LessonsApi } from "@/lib/lessons-api";
import type { QuestionResult, ScoreCard, TestSubmission } from "@/lib/types";

/** How one question went, for colouring and wording. */
export type Tone = "full" | "partial" | "none" | "pending";

export class TestResultView {
  /** "14 of 20 marks (70%)", or what is known so far while the open-ended answers are being graded. */
  static summary(card: ScoreCard): string {
    const { awarded, available, percent } = card.score;
    const text = `${awarded} of ${available} marks (${percent}%)`;
    return card.complete ? text : `${text} so far`;
  }

  static tone(row: QuestionResult): Tone {
    if (row.awarded === null) return "pending";
    if (row.awarded >= row.marks) return "full";
    return row.awarded > 0 ? "partial" : "none";
  }

  static label(row: QuestionResult): string {
    switch (TestResultView.tone(row)) {
      case "pending":
        return "Being graded";
      case "full":
        return "Full marks";
      default:
        return `${row.awarded} of ${row.marks} marks`;
    }
  }

  /** Who marked it, in words: a person reading "graded by model" should not mistake it for a person. */
  static source(row: QuestionResult): string {
    return row.graded_by === "model" ? "Graded by AI" : row.graded_by === "auto" ? "Marked automatically" : "";
  }

  static topics(card: ScoreCard): string {
    return card.topics_to_revisit.join(", ");
  }
}

export type FollowRun = (runId: string, onEnd: () => void) => () => void;

/**
 * Submits the lesson test and follows the grading to its end: the answers that could be marked at once are shown
 * straight away, and the card is updated when the open-ended ones are graded. The API and the way a run is followed
 * are constructor parameters, so a test drives it without a network.
 */
export class TestSubmitFlow {
  private stop: (() => void) | null = null;
  private disposed = false;

  constructor(
    private readonly api: Pick<LessonsApi, "submitTest" | "submission">,
    private readonly follow: FollowRun,
  ) {}

  /** Resolves with the submission as it ended (graded, or failed with its reason). `onUpdate` sees every state. */
  async run(lessonId: string, answers: Record<string, unknown>, onUpdate: (submission: TestSubmission) => void): Promise<TestSubmission> {
    const created = await this.api.submitTest(lessonId, answers);
    let submission = await this.api.submission(lessonId, created.submission_id);
    if (!this.disposed) onUpdate(submission);
    if (submission.status !== "grading" || !created.run_id) return submission;
    await new Promise<void>((resolve) => {
      if (this.disposed) return resolve();
      this.stop = this.follow(created.run_id!, resolve);
    });
    this.stop = null;
    submission = await this.api.submission(lessonId, created.submission_id);
    if (!this.disposed) onUpdate(submission);
    return submission;
  }

  /** Stop following (the page was left). Nothing more is reported. */
  dispose(): void {
    this.disposed = true;
    this.stop?.();
    this.stop = null;
  }
}
