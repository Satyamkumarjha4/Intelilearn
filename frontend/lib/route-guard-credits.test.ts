/**
 * Unit under test: `RouteGuard` for the credits pages (`/wallet`, `/streak`, `/buy`).
 *
 * Why: the wallet, the streak and the buy page show a learner's own credits, so a signed-out visitor must be sent to sign
 * in and brought back, and a learner who has not finished setting up must finish first. (The API authorises every
 * request anyway; this only picks the right page.)
 *
 * Use cases:
 * - a signed-out visitor on any of the three, or under them, is sent to sign in and brought back to where they were
 * - a signed-in learner who is not set up yet is sent to the setup, which carries on to the page
 * - a signed-in, set-up learner may be there
 */
import { describe, expect, test } from "bun:test";

import { RouteGuard } from "./route-guard";

describe.each(["/wallet", "/wallet/history", "/streak", "/buy"])("%s", (path) => {
  test("signed out goes to sign in and comes back", () => {
    expect(RouteGuard.redirectFor(path, "", { signedIn: false, onboarded: false })).toBe(`/auth?next=${encodeURIComponent(path)}`);
  });

  test("not set up goes to the setup first", () => {
    expect(RouteGuard.redirectFor(path, "", { signedIn: true, onboarded: false })).toBe(`/onboarding?next=${encodeURIComponent(path)}`);
  });

  test("set up may be there", () => {
    expect(RouteGuard.redirectFor(path, "", { signedIn: true, onboarded: true })).toBeNull();
  });
});
