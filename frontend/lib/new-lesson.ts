import { ApiError } from "@/lib/api";

const TRY_AGAIN = "We couldn't start that lesson. Please try again.";

/** The rules of the "What do you want to learn?" form. */
export class NewLesson {
  static readonly TOPIC_MAX = 200;
  static readonly CONTEXT_MAX = 1000;
  static readonly EXAMPLES = ["Binary search", "Photosynthesis", "Quadratic equations", "The French Revolution", "Newton's laws", "Python loops"];

  /** The quick check can start from two characters (not counting spaces around them). */
  static canStart(topic: string, busy: boolean): boolean {
    return !busy && topic.trim().length >= 2;
  }

  static counter(topic: string): string {
    return `${Math.min(topic.length, NewLesson.TOPIC_MAX)} / ${NewLesson.TOPIC_MAX}`;
  }

  /** Why a start was refused, in words that say what to do. */
  static errorMessage(error: unknown): string {
    if (!(error instanceof ApiError)) return TRY_AGAIN;
    if (error.code === "llm_not_configured") return "Lesson building is switched off right now. Please try again later.";
    if (error.code === "queue_unavailable") return "We couldn't reach our helper just now. Nothing was lost: please try again in a minute.";
    if (error.status === 429) return "You've started a lot of lessons just now. Please wait a little while, then try again.";
    const field = error.fields.topic?.[0] ?? error.fields.user_context?.[0];
    return field ?? TRY_AGAIN;
  }
}
