import { ApiError } from "@/lib/api";

/** 403 codes that mean "you are not allowed to see this", not "this action is not available to you". */
const NOT_A_REFUSAL = new Set(["permission_denied", "not_authenticated", "authentication_failed"]);

/** A refused action as a screen needs it: the words, where to buy more when that is the reason, and the numbers. */
export type Refusal = { message: string; buyPath: string | null; required: number | null; available: number | null };

/**
 * One way to say a refused action, for every screen that starts work that costs something (a new lesson, the choice
 * after a perfect quick check, a retake, a follow-up, a new quiz, a new sheet). The server's refusal is either
 * `ActionRefused` (a 403 whose own message is already written for the learner) or `InsufficientCredits` (a 402 with
 * code `insufficient_credits`, carrying `required` and `available`). Nothing raises either yet, so these screens will
 * show a refusal correctly the day something does.
 */
export class ActionRefusedMessage {
  static readonly FALLBACK = "That isn't available to you right now.";
  static readonly INSUFFICIENT_FALLBACK = "You don't have enough credits for that.";
  /** Where to buy more. The screen arrives in phase 10.5; until then it is the path it will have. */
  static readonly BUY_PATH = "/buy";
  private static readonly INSUFFICIENT_CODE = "insufficient_credits";

  /** Whether the error is the server saying no to the action, rather than to the person (not signed in, not theirs). */
  static isRefusal(error: unknown): error is ApiError {
    if (!(error instanceof ApiError)) return false;
    if (error.status === 402) return ActionRefusedMessage.isInsufficient(error);
    return error.status === 403 && !NOT_A_REFUSAL.has(error.code);
  }

  /** The words for a refusal, or null when the error is something else. */
  static of(error: unknown): string | null {
    return ActionRefusedMessage.refusal(error)?.message ?? null;
  }

  /** The words, the way to buy more (only for too few credits) and the numbers, or null when the error is something else. */
  static refusal(error: unknown): Refusal | null {
    if (!ActionRefusedMessage.isRefusal(error)) return null;
    if (!ActionRefusedMessage.isInsufficient(error)) {
      return { message: error.message.trim() || ActionRefusedMessage.FALLBACK, buyPath: null, required: null, available: null };
    }
    const required = ActionRefusedMessage.count(error.extra.required);
    const available = ActionRefusedMessage.count(error.extra.available);
    return { message: error.message.trim() || ActionRefusedMessage.shortOf(required, available), buyPath: ActionRefusedMessage.BUY_PATH, required, available };
  }

  private static isInsufficient(error: ApiError): boolean {
    return error.status === 402 && error.code === ActionRefusedMessage.INSUFFICIENT_CODE;
  }

  private static count(value: unknown): number | null {
    return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
  }

  private static shortOf(required: number | null, available: number | null): string {
    if (required === null || available === null) return ActionRefusedMessage.INSUFFICIENT_FALLBACK;
    return `You need ${required} ${required === 1 ? "credit" : "credits"} for that and have ${available}.`;
  }
}
