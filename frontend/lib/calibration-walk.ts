import { ApiError } from "@/lib/api";
import type { QuizzesApi } from "@/lib/quizzes-api";
import type { Calibration } from "@/lib/types";

export type WalkState =
  | { kind: "loading" }
  | { kind: "asking"; step: number; total: number; question: Extract<Calibration, { done: false }>["question"]; saving: boolean }
  | { kind: "done"; level: string }
  | { kind: "error"; message: string };

type Api = Pick<QuizzesApi, "calibration" | "answerCalibration">;

/**
 * The calibration warm-up from the learner's side: one question at a time, each answer final. The server holds the
 * questions and decides what comes next, so this only asks "what now?", sends an answer and shows what came back. An
 * answer sent twice (a double click) is one answer; an answer to a question the server has moved past (another tab) just
 * shows where the walk really is.
 */
export class CalibrationWalk {
  private current: WalkState = { kind: "loading" };

  constructor(
    private readonly api: Api,
    private readonly quizId: string,
    private readonly onChange: (state: WalkState) => void = () => undefined,
  ) {}

  get state(): WalkState {
    return this.current;
  }

  async start(): Promise<WalkState> {
    return this.settle(() => this.api.calibration(this.quizId));
  }

  /** `null` is "I don't know", which counts as a wrong answer on the server. */
  async answer(value: number | null): Promise<WalkState> {
    const asking = this.current;
    if (asking.kind !== "asking" || asking.saving) return this.current;
    this.set({ ...asking, saving: true });
    return this.settle(() => this.api.answerCalibration(this.quizId, asking.question.id, value), true);
  }

  private async settle(read: () => Promise<Calibration>, answering = false): Promise<WalkState> {
    try {
      this.set(CalibrationWalk.stateOf(await read()));
    } catch (error) {
      if (answering && error instanceof ApiError && error.status === 409) {
        return this.start(); // the walk had moved on or is over: show where it is
      }
      this.set({ kind: "error", message: error instanceof ApiError ? error.message : "We couldn't load the next question. Please try again." });
    }
    return this.current;
  }

  private set(state: WalkState): void {
    this.current = state;
    this.onChange(state);
  }

  static stateOf(calibration: Calibration): WalkState {
    return calibration.done
      ? { kind: "done", level: calibration.level }
      : { kind: "asking", step: calibration.step, total: calibration.total, question: calibration.question, saving: false };
  }
}
