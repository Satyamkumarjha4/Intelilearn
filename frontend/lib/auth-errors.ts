import { ApiError } from "@/lib/api";

const NETWORK = "We couldn't reach Socra. Check your connection and try again.";

/**
 * Every error the sign-in screens can meet, in plain words. A learner never reads a status, a code name or "ApiError":
 * the server's own sentence is kept for anything it said that is not listed here.
 */
export class AuthErrors {
  /** The one answer for every failed code: the same words whatever was wrong, so they say nothing about the address. */
  static readonly INVALID_CODE = "That code didn't work. Check it, or ask for a new one.";

  /** The sign-up check was missing or not passed (only when staff have switched it on). */
  static readonly CAPTCHA_FAILED = "Please complete the security check and try again.";

  static message(error: unknown): string {
    if (!(error instanceof ApiError)) return NETWORK;
    if (error.code === "invalid_credentials") return "That email and password don't match. Check them and try again.";
    if (error.code === "invalid_code") return AuthErrors.INVALID_CODE;
    if (error.code === "captcha_failed") return AuthErrors.CAPTCHA_FAILED;
    if (error.code === "verification_required") return "We sent you a code. Check your email to finish signing in.";
    if (error.status === 429) return `Too many tries. Please wait ${AuthErrors.wait(error.retryAfter)} and try again.`;
    return error.message;
  }

  /** What the sign-in page says when a sign-in with a provider came back refused (`/auth?error=<code>`). Every code has words;
   *  one nobody knows gets the general ones, and a staff or look-alike refusal says no more than "didn't work". */
  static callbackMessage(code: string | null | undefined): string | null {
    if (!code) return null;
    const words: Record<string, string> = {
      email_not_verified: "Google hasn't confirmed that email address, so we can't use it. Confirm it with Google, or create an account with a code instead.",
      provider_off: "That way of signing in isn't available right now. Please use your email.",
      state_mismatch: "That sign-in took too long or came from somewhere else. Please try again.",
      sign_in_failed: "We couldn't sign you in that way. Please try again, or use your email.",
      account_closed: "That account has been closed. If you think that's a mistake, please contact us.",
    };
    return words[code] ?? words.sign_in_failed;
  }

  /** The password was right but the email was never proved: a code is on its way and the next screen asks for it. */
  static needsCode(error: unknown): boolean {
    return error instanceof ApiError && error.code === "verification_required";
  }

  /** The wait the server asked for, in words. */
  static wait(seconds: number | null): string {
    if (seconds === null) return "a minute";
    if (seconds < 60) return `${seconds} ${seconds === 1 ? "second" : "seconds"}`;
    const minutes = Math.ceil(seconds / 60);
    return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  }
}
