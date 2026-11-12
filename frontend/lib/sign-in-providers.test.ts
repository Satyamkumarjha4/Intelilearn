/**
 * Unit under test: `SignInProviders`, which sign-in buttons to draw and where they go.
 *
 * Why: a button for a provider that is not set up leads a learner to an error page, and a list that fails to load must never
 * take the email form with it. The address that starts a sign-in carries where the learner was headed, but only when it is not
 * the usual place, and the provider's key goes into the path, so a malformed key must never be drawn.
 *
 * Use cases:
 * - the providers the server lists are returned; when the call fails or answers nonsense the list is empty
 * - entries without a usable key or label are dropped
 * - the start address has the provider in its path and `next` only when it is not the default, encoded
 * - the button says "Continue with <label>"
 */
import { describe, expect, test } from "bun:test";

import { ApiClient } from "./api";
import { SignInProviders } from "./sign-in-providers";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const clientAnswering = (answer: () => Response) => new ApiClient(async () => answer(), () => "csrf");

describe("load", () => {
  test("returns the providers the server lists", async () => {
    const providers = new SignInProviders(clientAnswering(() => json({ providers: [{ key: "google", label: "Google" }] })));

    expect(await providers.load()).toEqual([{ key: "google", label: "Google" }]);
  });

  test.each([
    ["a failed call", () => json({ detail: "x" }, 500)],
    ["a throttled call", () => json({ detail: "x" }, 429)],
    ["nonsense", () => json({ providers: "google" })],
    ["no list", () => json({})],
  ])("is empty after %s", async (_name, answer) => {
    expect(await new SignInProviders(clientAnswering(answer)).load()).toEqual([]);
  });

  test("is empty when the network fails", async () => {
    const client = new ApiClient(async () => { throw new TypeError("offline"); }, () => "csrf");

    expect(await new SignInProviders(client).load()).toEqual([]);
  });
});

describe("clean", () => {
  test("drops entries without a usable key or label", () => {
    expect(
      SignInProviders.clean([
        { key: "google", label: "Google" },
        { key: "Bad Key!", label: "x" },
        { key: "../../evil", label: "x" },
        { key: "microsoft", label: "" },
        { label: "No key" },
        null,
        "google",
      ]),
    ).toEqual([{ key: "google", label: "Google" }]);
  });

  test("anything that is not a list is empty", () => {
    expect(SignInProviders.clean(undefined)).toEqual([]);
    expect(SignInProviders.clean({ key: "google", label: "Google" })).toEqual([]);
  });
});

describe("startHref", () => {
  const google = { key: "google", label: "Google" };

  test("the provider is in the path, and the usual destination needs no next", () => {
    expect(SignInProviders.startHref(google, "/lessons")).toBe("/api/auth/oauth/google/start");
    expect(SignInProviders.startHref(google, "")).toBe("/api/auth/oauth/google/start");
  });

  test("where the learner was headed is kept, encoded", () => {
    expect(SignInProviders.startHref(google, "/quizzes/abc?tab=1&x=2")).toBe(`/api/auth/oauth/google/start?next=${encodeURIComponent("/quizzes/abc?tab=1&x=2")}`);
  });
});

test("the button says Continue with the provider's name", () => {
  expect(SignInProviders.buttonLabel({ key: "google", label: "Google" })).toBe("Continue with Google");
});
