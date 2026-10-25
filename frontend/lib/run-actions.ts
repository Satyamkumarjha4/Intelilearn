import { ApiError } from "@/lib/api";
import type { ConsoleApi } from "@/lib/console-api";

export type ActionResult = { ok: true; message: string; runId: string | null } | { ok: false; message: string };

const REFUSALS: Record<string, string> = {
  wrong_stage: "That lesson has not failed (any more), so there is nothing to retry.",
  run_in_progress: "This lesson already has a run going. Give it a moment, then look again.",
  not_retryable: "Only a lesson build can be retried. A study sheet, repair or grading run starts again from the lesson.",
  run_ended: "This run has already ended.",
};

/**
 * Retry and Stop on a run, as staff. Each says what happened in a sentence for a toast; a refusal (the console
 * answers 409 with a code) is explained rather than shown as the API wrote it.
 */
export class RunActions {
  constructor(private readonly api: Pick<ConsoleApi, "retryRun" | "cancelRun">) {}

  retry(id: string): Promise<ActionResult> {
    return this.attempt(async () => {
      const { run_id } = await this.api.retryRun(id);
      return { ok: true, message: "Retry started from the last checkpoint.", runId: run_id };
    });
  }

  cancel(id: string): Promise<ActionResult> {
    return this.attempt(async () => {
      await this.api.cancelRun(id);
      return { ok: true, message: "The run will stop after its current step.", runId: null };
    });
  }

  private async attempt(action: () => Promise<ActionResult>): Promise<ActionResult> {
    try {
      return await action();
    } catch (error) {
      return { ok: false, message: RunActions.explain(error) };
    }
  }

  private static explain(error: unknown): string {
    if (!(error instanceof ApiError)) return "That did not work. Check your connection and try again.";
    if (error.status === 409 && REFUSALS[error.code]) return REFUSALS[error.code];
    if (error.status === 404) return "That run is not there any more. Refresh the list.";
    if (error.status === 429) {
      const wait = error.retryAfter ? `${error.retryAfter} seconds` : "a moment";
      return `Too many requests in a row. Try again in ${wait}.`;
    }
    return error.message;
  }
}
