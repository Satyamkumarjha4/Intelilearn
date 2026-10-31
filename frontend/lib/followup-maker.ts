import { ActionRefusedMessage } from "@/lib/action-refused";
import { ApiError } from "@/lib/api";
import type { LessonsApi } from "@/lib/lessons-api";
import type { FollowupLevel } from "@/lib/types";

/** Where the learner goes, or why they stay. */
export type FollowupResult = { kind: "open"; lessonId: string } | { kind: "failed"; message: string };

/**
 * Makes a Foundation or Advanced lesson from the one on screen and says which lesson to open. The server makes at most
 * one of each level, so "it already exists" is not a failure: the answer names that lesson and the learner is taken to
 * it, which also makes a double click, or an offer that went stale, harmless.
 */
export class FollowupMaker {
  constructor(private readonly api: Pick<LessonsApi, "makeFollowup">) {}

  async make(lessonId: string, level: FollowupLevel): Promise<FollowupResult> {
    try {
      const made = await this.api.makeFollowup(lessonId, level);
      return { kind: "open", lessonId: made.lesson_id };
    } catch (error) {
      const existing = FollowupMaker.existing(error);
      return existing ? { kind: "open", lessonId: existing } : { kind: "failed", message: FollowupMaker.message(error) };
    }
  }

  /** The id of the lesson that was already there, from a `409 already_exists`. */
  static existing(error: unknown): string | null {
    if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "already_exists") return null;
    const id = error.extra.lesson_id;
    return typeof id === "string" && id ? id : null;
  }

  /** Why no lesson was made, in words that say what to do. */
  static message(error: unknown): string {
    const refused = ActionRefusedMessage.of(error);
    if (refused) return refused;
    if (error instanceof ApiError && error.status === 429) return "You've started a lot of lessons just now. Please wait a little while and try again.";
    if (error instanceof ApiError && error.code === "llm_not_configured") return "Lesson building is switched off right now. Please try again later.";
    if (error instanceof ApiError && error.code === "wrong_stage") return "That lesson isn't ready yet. Try again in a moment.";
    return "We couldn't make that lesson. Please try again.";
  }
}
