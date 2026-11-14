import { ApiError } from "@/lib/api";

import { SigninWords } from "./forms";

/** The words for a refused sign-in action. A 409 carries a code the screen can say; a 400 for the reason names the field. */
export class SigninFailure {
  /** A sentence for this failure when it is one of the sign-in refusals or a missing reason; undefined otherwise. */
  static message(error: unknown): string | undefined {
    if (!(error instanceof ApiError)) return undefined;
    if (error.status === 409) return SigninWords.refusal(error.code, error.message);
    const reason = error.fields.reason?.[0];
    return error.status === 400 && reason ? reason : undefined;
  }
}
