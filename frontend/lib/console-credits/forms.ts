/** The amount of a hand-made change to a wallet: a whole number of credits other than zero, with a sign if it takes. */
export class AdjustForm {
  static readonly REASON_MAX = 500;

  static amount(text: string): number | null {
    const trimmed = text.trim();
    if (!/^[+-]?\d{1,7}$/.test(trimmed)) return null;
    const number = Number(trimmed);
    return number === 0 ? null : number;
  }

  /** What is wrong with the form, by field (nothing when it can be sent). The reason is required. */
  static errors(amount: string, reason: string): { amount?: string; reason?: string } {
    const found: { amount?: string; reason?: string } = {};
    if (AdjustForm.amount(amount) === null) found.amount = "Enter a whole number of credits other than zero. A minus takes credits.";
    if (!reason.trim()) found.reason = "Say why the credits are being given or taken.";
    else if (reason.trim().length > AdjustForm.REASON_MAX) found.reason = `At most ${AdjustForm.REASON_MAX} characters.`;
    return found;
  }

  /** The words for what pressing the button will do. */
  static summary(amount: string): string {
    const number = AdjustForm.amount(amount);
    if (number === null) return "Give or take credits";
    const credits = Math.abs(number) === 1 ? "credit" : "credits";
    return number > 0 ? `Give ${number} ${credits}` : `Take ${-number} ${credits}`;
  }
}

/** The rupees typed in a refund box: blank is "all that remains", else a positive amount to the paisa. */
export class RefundForm {
  static amount(text: string): { ok: true; rupees: string } | { ok: false; error: string } {
    const trimmed = text.trim();
    if (trimmed === "") return { ok: true, rupees: "" };
    if (!/^\d{1,7}(\.\d{1,2})?$/.test(trimmed) || Number(trimmed) <= 0) {
      return { ok: false, error: "Enter the amount in rupees, like 12.50, or leave it empty for all that remains." };
    }
    return { ok: true, rupees: trimmed };
  }

  /** What is sent: the form's token, and the rupees only when some were typed. */
  static body(token: string, rupees: string): { token: string; amount?: string } {
    return rupees ? { token, amount: rupees } : { token };
  }
}

/** Deleting a learner's data cannot be undone, so the person at the keyboard types the account's email first. */
export class EraseForm {
  /** Whether what was typed is the account's email: any case, spaces around it ignored, nothing else. */
  static matches(typed: string, email: string): boolean {
    return email.trim() !== "" && typed.trim().toLowerCase() === email.trim().toLowerCase();
  }

  /** The words for why an account cannot be erased from here, by the API's code ("" when it can). */
  static blocked(code: string): string {
    switch (code) {
      case "cannot_erase_self":
        return "This is your own account. It cannot be erased from the console.";
      case "staff_account":
        return "This is a staff account. Remove its staff access in the Django admin first, then erase it here.";
      case "already_erased":
        return "This account has already been erased. Nothing is left to delete.";
      default:
        return "";
    }
  }

  /** One line for what the delete took away, from the API's counts. */
  static done(result: { lessons: number; quizzes: number; credits_forfeited: number; refresh_tokens: number }): string {
    const lessons = `${result.lessons} ${result.lessons === 1 ? "lesson" : "lessons"}`;
    const quizzes = `${result.quizzes} ${result.quizzes === 1 ? "quiz" : "quizzes"}`;
    const credits = `${result.credits_forfeited} ${result.credits_forfeited === 1 ? "credit" : "credits"}`;
    return `Erased: ${lessons}, ${quizzes}, ${credits} written off, sign-ins ended.`;
  }
}
