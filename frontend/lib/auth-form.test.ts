/**
 * Unit under test: `AuthRules`, the rules of the sign-in and create-account form.
 *
 * Why: this form is the front door. A check that lets a bad email through wastes a request and a throttle slot; a
 * password checklist that ticks the wrong thing teaches the wrong rule; an error that says "401" or "ApiError" is no
 * help; and a lost `next` sends a learner to the wrong page after signing up.
 *
 * Use cases:
 * - sign in needs an email that looks like one and a password; create account also needs a name that is not blank, a
 *   password that meets the two rules the server enforces (8 characters, not only numbers), and the confirmation that
 *   the person is 18 or older or has a parent's or guardian's agreement
 * - the password checklist ticks "At least 8 characters" and "Not only numbers" as they are met, and always lists the
 *   common-password rule as something checked later
 * - a wrong email or password, too many tries (with or without a wait time), no network, and anything else each get
 *   plain words; the server's own message is kept for anything else it said
 * - after signing in the learner goes to where they were headed, or through onboarding first when their profile is
 *   incomplete (keeping where they were headed)
 * - each mode has its copy, its pending label, its switch link and its page title
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { AuthRules } from "./auth-form";

describe("validate", () => {
  test("sign in needs an email and a password", () => {
    expect(AuthRules.validate("login", { name: "", email: "ada@example.com", password: "x" })).toEqual({});
    expect(AuthRules.validate("login", { name: "", email: "", password: "" })).toEqual({
      email: ["Enter your email address."],
      password: ["Enter your password."],
    });
  });

  test.each([["ada"], ["ada@"], ["@example.com"], ["ada@example"], ["ada example@x.com"]])("%p is not an email", (email) => {
    expect(AuthRules.validate("login", { name: "", email, password: "x" }).email).toEqual(["That doesn't look like an email address."]);
  });

  test("create account also needs a name and a password that meets the rules", () => {
    const errors = AuthRules.validate("register", { name: "  ", email: "ada@example.com", password: "1234567", acceptedTerms: true });

    expect(errors).toEqual({
      name: ["Tell us your name."],
      password: ["Use at least 8 characters."],
    });
    expect(AuthRules.validate("register", { name: "Ada", email: "ada@example.com", password: "12345678", acceptedTerms: true })).toEqual({ password: ["Use more than numbers."] });
    expect(AuthRules.validate("register", { name: "Ada", email: "ada@example.com", password: "tulip-garden-7", acceptedTerms: true })).toEqual({});
  });

  test("create account needs the confirmation, and sign in does not", () => {
    const person = { name: "Ada", email: "ada@example.com", password: "tulip-garden-7" };

    expect(AuthRules.validate("register", person)).toEqual({ accept_terms: ["Please confirm to continue."] });
    expect(AuthRules.validate("register", { ...person, acceptedTerms: false })).toEqual({ accept_terms: ["Please confirm to continue."] });
    expect(AuthRules.validate("login", person)).toEqual({});
  });
});

describe("password checklist", () => {
  test("ticks each rule as it is met", () => {
    const met = (password: string) => AuthRules.checklist(password).map((item) => item.met);

    expect(met("")).toEqual([false, false, null]);
    expect(met("abc")).toEqual([false, true, null]);
    expect(met("12345678")).toEqual([true, false, null]);
    expect(met("abcdefg1")).toEqual([true, true, null]);
  });

  test("lists the common-password rule as checked later", () => {
    expect(AuthRules.checklist("x").map((item) => item.label)).toEqual([
      "At least 8 characters",
      "Not only numbers",
      "Not a common password (we check when you continue)",
    ]);
  });
});

describe("error messages", () => {
  test("a wrong email or password", () => {
    expect(AuthRules.errorMessage(new ApiError(401, "invalid_credentials", "Invalid email or password."))).toBe(
      "That email and password don't match. Check them and try again.",
    );
  });

  test("too many tries, with the wait when the server said", () => {
    expect(AuthRules.errorMessage(new ApiError(429, "throttled", "x"))).toBe("Too many tries. Please wait a minute and try again.");
    expect(AuthRules.errorMessage(new ApiError(429, "throttled", "x", {}, {}, 30))).toBe("Too many tries. Please wait 30 seconds and try again.");
    expect(AuthRules.errorMessage(new ApiError(429, "throttled", "x", {}, {}, 1))).toBe("Too many tries. Please wait 1 second and try again.");
    expect(AuthRules.errorMessage(new ApiError(429, "throttled", "x", {}, {}, 150))).toBe("Too many tries. Please wait 3 minutes and try again.");
  });

  test("no network, or anything that is not an API error", () => {
    expect(AuthRules.errorMessage(new TypeError("Failed to fetch"))).toBe("We couldn't reach Socra. Check your connection and try again.");
    expect(AuthRules.errorMessage(undefined)).toBe("We couldn't reach Socra. Check your connection and try again.");
  });

  test("anything else the server said is kept", () => {
    expect(AuthRules.errorMessage(new ApiError(400, "invalid", "Please correct the highlighted fields."))).toBe("Please correct the highlighted fields.");
  });
});

describe("destination", () => {
  test("a learner with a complete profile goes where they were headed", () => {
    expect(AuthRules.destination(true, "/lessons/abc")).toBe("/lessons/abc");
  });

  test("one with an incomplete profile goes through onboarding, which carries on to where they were headed", () => {
    expect(AuthRules.destination(false, "/lessons/abc?tab=test")).toBe("/onboarding?next=%2Flessons%2Fabc%3Ftab%3Dtest");
  });

  test("the usual place needs no next", () => {
    expect(AuthRules.destination(false, "/lessons")).toBe("/onboarding");
    expect(AuthRules.destination(true, "/lessons")).toBe("/lessons");
  });
});

describe("copy", () => {
  test("each mode has its words", () => {
    expect(AuthRules.COPY.login).toMatchObject({ title: "Welcome back", description: "Sign in to carry on learning.", panel: "Good to see you again.", submit: "Sign in", pending: "Signing in…", pageTitle: "Sign in", switchLink: "New here? Create an account" });
    expect(AuthRules.COPY.register).toMatchObject({ title: "Create your account", panel: "Learn only what you don't know yet.", submit: "Create account", pending: "Creating your account…", pageTitle: "Create account", switchLink: "Already have an account? Sign in" });
    expect(AuthRules.STEPS).toEqual(["A 10-question quick check on any topic", "See your starting point", "An interactive lesson made for you"]);
  });

  test("the address for each mode keeps where the learner was headed", () => {
    expect(AuthRules.href("login", "/lessons")).toBe("/auth");
    expect(AuthRules.href("register", "/lessons")).toBe("/auth?mode=register");
    expect(AuthRules.href("login", "/lessons/abc")).toBe("/auth?next=%2Flessons%2Fabc");
    expect(AuthRules.href("register", "/lessons/abc")).toBe("/auth?mode=register&next=%2Flessons%2Fabc");
  });
});
