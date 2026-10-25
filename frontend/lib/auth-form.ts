import { ApiError, type FieldErrors } from "@/lib/api";

export type Mode = "login" | "register";
export type Values = { name: string; email: string; password: string; acceptedTerms?: boolean };
export type CheckItem = { label: string; /** null: not checked here (the server does it) */ met: boolean | null };

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const NETWORK = "We couldn't reach Socra. Check your connection and try again.";

/** The rules of the sign-in and create-account form. The server stays the authority: this only saves a round trip. */
export class AuthRules {
  static readonly DEFAULT_NEXT = "/lessons";
  /** The same words the server uses when the confirmation is missing. */
  static readonly CONSENT_MESSAGE = "Please confirm to continue.";
  /** Many learners are under 18, so a grown-up's agreement counts. */
  static readonly CONSENT_LABEL = "I'm 18 or older, or my parent or guardian has agreed to Socra's";

  static readonly COPY = {
    login: {
      title: "Welcome back",
      description: "Sign in to carry on learning.",
      panel: "Good to see you again.",
      submit: "Sign in",
      pending: "Signing in…",
      pageTitle: "Sign in",
      switchLink: "New here? Create an account",
    },
    register: {
      title: "Create your account",
      description: "We'll find out what you already know, then teach you the rest.",
      panel: "Learn only what you don't know yet.",
      submit: "Create account",
      pending: "Creating your account…",
      pageTitle: "Create account",
      switchLink: "Already have an account? Sign in",
    },
  } as const;

  static readonly STEPS = ["A 10-question quick check on any topic", "See your starting point", "An interactive lesson made for you"] as const;

  static validate(mode: Mode, values: Values): FieldErrors {
    const errors: FieldErrors = {};
    if (mode === "register" && !values.name.trim()) errors.name = ["Tell us your name."];
    if (!values.email.trim()) errors.email = ["Enter your email address."];
    else if (!EMAIL.test(values.email.trim())) errors.email = ["That doesn't look like an email address."];
    if (mode === "register" && !values.acceptedTerms) errors.accept_terms = [AuthRules.CONSENT_MESSAGE];
    if (!values.password) errors.password = ["Enter your password."];
    else if (mode === "register") {
      if (values.password.length < 8) errors.password = ["Use at least 8 characters."];
      else if (/^\d+$/.test(values.password)) errors.password = ["Use more than numbers."];
    }
    return errors;
  }

  /** The password rules, ticked as they are met. The common-password rule is only the server's to check. */
  static checklist(password: string): CheckItem[] {
    return [
      { label: "At least 8 characters", met: password.length >= 8 },
      { label: "Not only numbers", met: password.length > 0 && !/^\d+$/.test(password) },
      { label: "Not a common password (we check when you continue)", met: null },
    ];
  }

  static errorMessage(error: unknown): string {
    if (!(error instanceof ApiError)) return NETWORK;
    if (error.code === "invalid_credentials") return "That email and password don't match. Check them and try again.";
    if (error.status === 429) return `Too many tries. Please wait ${AuthRules.wait(error.retryAfter)} and try again.`;
    return error.message;
  }

  /** Where to go once signed in: on to `next`, through onboarding first (which carries on to `next`) if the profile is incomplete. */
  static destination(profileComplete: boolean, next: string): string {
    if (profileComplete) return next;
    return next === AuthRules.DEFAULT_NEXT ? "/onboarding" : `/onboarding?next=${encodeURIComponent(next)}`;
  }

  /** The address of a mode of the form, keeping where the learner was headed. */
  static href(mode: Mode, next: string): string {
    const params = new URLSearchParams();
    if (mode === "register") params.set("mode", "register");
    if (next !== AuthRules.DEFAULT_NEXT) params.set("next", next);
    const text = params.toString();
    return text ? `/auth?${text}` : "/auth";
  }

  private static wait(seconds: number | null): string {
    if (seconds === null) return "a minute";
    if (seconds < 60) return `${seconds} ${seconds === 1 ? "second" : "seconds"}`;
    const minutes = Math.ceil(seconds / 60);
    return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  }
}
