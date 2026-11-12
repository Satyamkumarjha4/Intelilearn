import { ApiError } from "@/lib/api";

const NETWORK = "We couldn't reach Socra. Check your connection and try again.";

/**
 * Every error the sign-in screens can meet, in plain words. A learner never reads a status, a code name or "ApiError":
 * the server's own sentence is kept for anything it said that is not listed here.
 */
export class AuthErrors {
  /** The one answer for every failed code: the same words whatever was wrong, so they say nothing about the address. */
  static readonly INVALID_CODE = "That code didn't work. Check it, or ask for a new one.";

  static message(error: unknown): string {
    if (!(error instanceof ApiError)) return NETWORK;
    if (error.code === "invalid_credentials") return "That email and password don't match. Check them and try again.";
    if (error.code === "invalid_code") return AuthErrors.INVALID_CODE;
    if (error.code === "verification_required") return "We sent you a code. Check your email to finish signing in.";
    if (error.status === 429) return `Too many tries. Please wait ${AuthErrors.wait(error.retryAfter)} and try again.`;
    return error.message;
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
