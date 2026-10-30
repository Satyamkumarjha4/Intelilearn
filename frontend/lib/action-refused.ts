import { ApiError } from "@/lib/api";

/** 403 codes that mean "you are not allowed to see this", not "this action is not available to you". */
const NOT_A_REFUSAL = new Set(["permission_denied", "not_authenticated", "authentication_failed"]);

/**
 * One way to say a refused action, for every screen that starts work that may later cost something (a new lesson, the
 * choice after a perfect quick check, a retake, a follow-up, a new quiz, a new sheet). The server's refusal
 * (`ActionRefused`) is a 403 whose own message is already written for the learner; nothing raises it yet, so these
 * screens will show a refusal correctly the day something does.
 */
export class ActionRefusedMessage {
  static readonly FALLBACK = "That isn't available to you right now.";

  /** Whether the error is the server saying no to the action, rather than to the person (not signed in, not theirs). */
  static isRefusal(error: unknown): error is ApiError {
    return error instanceof ApiError && error.status === 403 && !NOT_A_REFUSAL.has(error.code);
  }

  /** The words for a refusal, or null when the error is something else. */
  static of(error: unknown): string | null {
    if (!ActionRefusedMessage.isRefusal(error)) return null;
    return error.message.trim() || ActionRefusedMessage.FALLBACK;
  }
}
