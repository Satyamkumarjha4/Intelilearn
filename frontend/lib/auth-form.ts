import type { FieldErrors } from "@/lib/api";
import { AuthErrors } from "@/lib/auth-errors";
import { CodeEntry } from "@/lib/code-entry";
import type { CodePurpose } from "@/lib/auth-api";

export type Mode = "login" | "register";
export type Values = { name: string; email: string; password: string; acceptedTerms?: boolean };
export type CheckItem = { label: string; /** null: not checked here (the server does it) */ met: boolean | null };

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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

  static readonly VERIFY = {
    title: "Check your email",
    pageTitle: "Check your email",
    submit: "Continue",
    pending: "Checking…",
    label: "6-digit code",
    hint: "Can't find it? Look in your spam or junk folder.",
    different: "Use a different email",
    lost: "We've lost track of where we sent your code.",
    start: "Start again",
  } as const;

  /** The sentence under the heading: where the code went. */
  static verifyDescription(email: string): string {
    return `We sent a 6-digit code to ${email}. Enter it below. It only works for a short while.`;
  }

  static readonly FORGOT = {
    title: "Forgot your password?",
    pageTitle: "Forgot password",
    description: "Tell us your email and we'll send you a code to choose a new one.",
    submit: "Send me a code",
    pending: "Sending…",
    link: "Forgot password?",
    back: "Back to sign in",
  } as const;

  static readonly RESET = {
    title: "Choose a new password",
    pageTitle: "New password",
    label: "6-digit code",
    password: "New password",
    submit: "Save and sign in",
    pending: "Saving…",
    hint: "Can't find it? Look in your spam or junk folder.",
    different: "Use a different email",
    lost: "We've lost track of where we sent your code.",
    start: "Start again",
  } as const;

  /** The sentence under the heading of the new-password screen. It never says the address has an account: it is the same for every address. */
  static resetDescription(email: string): string {
    return `If ${email} has an account, we've sent a 6-digit code to it. Enter it below, then choose a new password.`;
  }

  /** The address of the forgot-password screen, keeping where the learner was headed. */
  static forgotHref(next: string): string {
    return next === AuthRules.DEFAULT_NEXT ? "/auth/forgot" : `/auth/forgot?next=${encodeURIComponent(next)}`;
  }

  /** The address of the new-password screen, keeping where the learner was headed. */
  static resetHref(next: string): string {
    return next === AuthRules.DEFAULT_NEXT ? "/auth/reset" : `/auth/reset?next=${encodeURIComponent(next)}`;
  }

  /** Checks before asking for a code: an email that looks like one. */
  static validateForgot(email: string): FieldErrors {
    if (!email.trim()) return { email: ["Enter your email address."] };
    return EMAIL.test(email.trim()) ? {} : { email: ["That doesn't look like an email address."] };
  }

  /** Checks before saving a new password: a whole code and the two password rules the server enforces. */
  static validateReset(code: string, password: string): FieldErrors {
    const errors: FieldErrors = {};
    if (!CodeEntry.isComplete(code)) errors.code = ["Enter the 6-digit code from your email."];
    if (!password) errors.new_password = ["Choose a new password."];
    else if (password.length < 8) errors.new_password = ["Use at least 8 characters."];
    else if (/^\d+$/.test(password)) errors.new_password = ["Use more than numbers."];
    return errors;
  }

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

  /** The create-account request. The browser's zone sets the learner's day (credits plan D9); the server ignores a name it does not know. */
  static registerBody(person: { name: string; email: string; password: string }, acceptTerms: boolean, zone: string | null) {
    return { ...person, accept_terms: acceptTerms, ...(zone ? { timezone: zone } : {}) };
  }

  static errorMessage(error: unknown): string {
    return AuthErrors.message(error);
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

  /** The "Check your email" screen, keeping where the learner was headed. A sign-in that asked for a code says so (`purpose`). */
  static verifyHref(next: string, purpose: CodePurpose = "signup"): string {
    const params = new URLSearchParams();
    if (purpose === "login") params.set("purpose", "login");
    if (next !== AuthRules.DEFAULT_NEXT) params.set("next", next);
    const text = params.toString();
    return text ? `/auth/verify?${text}` : "/auth/verify";
  }

  /** The purpose a verify screen was opened for: anything but `login` is a sign-up. */
  static purposeOf(value: string | string[] | undefined): CodePurpose {
    return value === "login" ? "login" : "signup";
  }
}
