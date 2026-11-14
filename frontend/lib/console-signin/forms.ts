/** The reason staff type when they vouch for a person (mark verified, approve a sign-up). The server holds the same
 *  rule (10 characters at least); this only says so before a request is made. */
export class ReasonForm {
  static readonly MIN = 10;
  static readonly MAX = 500;

  /** What is wrong with the reason, or undefined when it can be sent. */
  static error(reason: string): string | undefined {
    const length = reason.trim().length;
    if (length < ReasonForm.MIN) return `Say why, in at least ${ReasonForm.MIN} characters. It is kept in the change log.`;
    if (length > ReasonForm.MAX) return `At most ${ReasonForm.MAX} characters.`;
    return undefined;
  }
}

/** The words the sign-in screens use for the API's codes and states, so a screen never prints a raw value. */
export class SigninWords {
  private static readonly SOURCES: Record<string, string> = {
    code: "Proved with a code",
    google: "Proved by Google",
    microsoft: "Proved by Microsoft",
    staff: "Marked by staff",
    operator: "Made by an operator",
    legacy: "Existed before verification, never proved",
    "": "Not verified",
  };
  private static readonly CODE_STATES: Record<string, string> = {
    live: "Waiting to be used",
    used: "Used",
    cancelled: "Cancelled by a newer code",
    dead: "Used up (too many wrong tries)",
    expired: "Ran out of time",
  };
  private static readonly PURPOSES: Record<string, string> = { signup: "Sign-up", login: "Sign-in", reset: "Password reset" };
  private static readonly METHODS: Record<string, string> = { code: "Email and code", google: "Google", microsoft: "Microsoft", staff: "Approved by staff" };
  private static readonly REFUSALS: Record<string, string> = {
    already_verified: "This account is already verified.",
    account_closed: "This account is closed.",
    account_erased: "This account has been erased.",
    nothing_to_unlock: "Nothing to unlock: the email is not locked and has no live code.",
    not_locked: "Nothing to unlock: the email is not locked and has no live code.",
    expired: "This sign-up has expired. The person has to register again.",
    account_exists: "An account already has this email.",
    captcha_not_configured: "Set the Turnstile keys in the environment first.",
  };

  /** "15 Mar, 12:30" in UTC (the console counts days in UTC); "" for a missing or unreadable time. */
  static when(iso: string | null | undefined): string {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const day = date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
    const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
    return `${day}, ${time}`;
  }

  static source(source: string): string {
    return SigninWords.SOURCES[source] ?? source;
  }
  static codeState(state: string): string {
    return SigninWords.CODE_STATES[state] ?? state;
  }
  static purpose(purpose: string): string {
    return SigninWords.PURPOSES[purpose] ?? purpose;
  }
  static method(method: string): string {
    return SigninWords.METHODS[method] ?? method;
  }
  /** A sentence for the API's refusal code, or the server's own message when the code is not one of these. */
  static refusal(code: string | undefined, fallback: string): string {
    return (code && SigninWords.REFUSALS[code]) || fallback;
  }
  /** How the person can sign in, as words ("Password and Google"); a person with no way in is said to have none. */
  static methods(methods: readonly string[]): string {
    if (methods.length === 0) return "No way to sign in yet (they can choose a password with “Forgot password”)";
    const names = methods.map((m) => (m === "password" ? "Password" : SigninWords.METHODS[m] ?? m));
    return names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  }
}

/** The abuse board's rows: what is worth a second look. */
export class AbuseSummary {
  /** Totals over the days shown. */
  static totals(days: readonly { accounts_made: number; codes_sent: number; failed_checks: number; disposable_refused: number; captcha_failed: number }[]) {
    return days.reduce(
      (sum, d) => ({
        accounts_made: sum.accounts_made + d.accounts_made,
        codes_sent: sum.codes_sent + d.codes_sent,
        failed_checks: sum.failed_checks + d.failed_checks,
        disposable_refused: sum.disposable_refused + d.disposable_refused,
        captcha_failed: sum.captcha_failed + d.captcha_failed,
      }),
      { accounts_made: 0, codes_sent: 0, failed_checks: 0, disposable_refused: 0, captcha_failed: 0 },
    );
  }

  /** The tallest bar, never zero, so a chart of quiet days does not divide by it. */
  static peak(values: readonly number[]): number {
    return Math.max(1, ...values);
  }
}
