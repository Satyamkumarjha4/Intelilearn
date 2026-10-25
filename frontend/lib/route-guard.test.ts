/**
 * Unit under test: `RouteGuard`, the decision `proxy.ts` makes about where a visitor may be.
 *
 * Why: the guard is what keeps the landing page for people who are not signed in and the app for people who are. It
 * only reads the marker cookies the API sets (the API still authorises everything), so a wrong turn here sends a
 * learner to a page that is not theirs or traps them in a redirect loop.
 *
 * Use cases:
 * - "/" is the landing page for a signed-out visitor
 * - a signed-in visitor to "/" goes to their lessons, or to onboarding if they have not finished it
 * - "/auth" is open to a signed-out visitor; a signed-in one is sent on like "/" does, to `next` when it is a safe path on
 *   this site (an address that could leave the site is ignored, however it is encoded)
 * - the app pages ("/lessons", "/profile", "/onboarding" and what is under them) send a signed-out visitor to
 *   "/auth" with `next` set to where they were going, query string included
 * - a signed-in visitor who has not been onboarded is sent to "/onboarding" from the other app pages, with the page they
 *   wanted kept as `next`, and stays on it
 * - a visitor who has been onboarded is sent from "/onboarding" to `next` or their lessons, unless they are in the last
 *   step of the setup (the profile is saved at step 4, so a refresh on step 5 must not throw them out)
 * - a signed-in, onboarded visitor goes through
 * - the staff console ("/console" and what is under it) needs a signed-in visitor, and sends a signed-out one to
 *   "/auth" like the app does, but does not ask staff to finish onboarding first (the API decides who is staff)
 * - paths the guard does not know are left alone, and a look-alike prefix ("/lessonsfoo") is not an app page
 */
import { describe, expect, test } from "bun:test";

import { RouteGuard } from "./route-guard";

const out = { signedIn: false, onboarded: false };
const half = { signedIn: true, onboarded: false };
const full = { signedIn: true, onboarded: true };
const finishing = { signedIn: true, onboarded: true, settingUp: true };

describe("RouteGuard", () => {
  test("a signed-out visitor sees the landing page at /", () => {
    expect(RouteGuard.redirectFor("/", "", out)).toBeNull();
  });

  test.each([
    [full, "/lessons"],
    [half, "/onboarding"],
  ])("a signed-in visitor to / is sent on (%p)", (visitor, target) => {
    expect(RouteGuard.redirectFor("/", "", visitor)).toBe(target);
  });

  test("a signed-out visitor may open /auth, a signed-in one is sent on", () => {
    expect(RouteGuard.redirectFor("/auth", "", out)).toBeNull();
    expect(RouteGuard.redirectFor("/auth", "", full)).toBe("/lessons");
    expect(RouteGuard.redirectFor("/auth", "", half)).toBe("/onboarding");
  });

  test("a signed-in visitor sent from /auth goes where they were headed", () => {
    const search = `?next=${encodeURIComponent("/lessons/abc?tab=test")}`;

    expect(RouteGuard.redirectFor("/auth", search, full)).toBe("/lessons/abc?tab=test");
    expect(RouteGuard.redirectFor("/auth", search, half)).toBe(`/onboarding?next=${encodeURIComponent("/lessons/abc?tab=test")}`);
  });

  test.each([
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "/\t/evil.example",
    "%2F%2Fevil.example",
    "javascript:alert(1)",
    "",
  ])("a next of %j is ignored when sending a signed-in visitor on", (next) => {
    const search = `?next=${encodeURIComponent(next)}`;

    expect(RouteGuard.redirectFor("/auth", search, full)).toBe("/lessons");
    expect(RouteGuard.redirectFor("/auth", search, half)).toBe("/onboarding");
  });

  test.each(["/lessons", "/lessons/abc", "/profile", "/onboarding"])("a signed-out visitor to %s is asked to sign in first", (path) => {
    expect(RouteGuard.redirectFor(path, "", out)).toBe(`/auth?next=${encodeURIComponent(path)}`);
  });

  test("the way back keeps the query string", () => {
    expect(RouteGuard.redirectFor("/lessons/new", "?topic=a b", out)).toBe(`/auth?next=${encodeURIComponent("/lessons/new?topic=a b")}`);
  });

  test("a visitor who has not been onboarded is sent to onboarding, and stays there", () => {
    expect(RouteGuard.redirectFor("/lessons", "", half)).toBe("/onboarding");
    expect(RouteGuard.redirectFor("/onboarding", "", half)).toBeNull();
  });

  test("the page a not-yet-onboarded visitor wanted is kept for after the setup", () => {
    expect(RouteGuard.redirectFor("/profile", "", half)).toBe(`/onboarding?next=${encodeURIComponent("/profile")}`);
    expect(RouteGuard.redirectFor("/lessons/new", "?topic=a b", half)).toBe(`/onboarding?next=${encodeURIComponent("/lessons/new?topic=a b")}`);
  });

  test("a signed-in, onboarded visitor goes through to the app", () => {
    expect(RouteGuard.redirectFor("/lessons/abc", "", full)).toBeNull();
    expect(RouteGuard.redirectFor("/profile", "", full)).toBeNull();
  });

  test("an onboarded visitor has nothing left to set up, so /onboarding sends them on to next or their lessons", () => {
    expect(RouteGuard.redirectFor("/onboarding", "?next=%2Flessons%2Fnew", full)).toBe("/lessons/new");
    expect(RouteGuard.redirectFor("/onboarding", "", full)).toBe("/lessons");
    expect(RouteGuard.redirectFor("/onboarding", "?next=https%3A%2F%2Fevil.example", full)).toBe("/lessons");
  });

  test("a visitor in the last step of the setup may refresh it: the profile is already saved", () => {
    expect(RouteGuard.redirectFor("/onboarding", "", finishing)).toBeNull();
    expect(RouteGuard.redirectFor("/lessons", "", finishing)).toBeNull();
  });

  test.each(["/console", "/console/runs"])("a signed-out visitor to %s is asked to sign in, and the way back keeps the query", (path) => {
    expect(RouteGuard.redirectFor(path, "?run=1", out)).toBe(`/auth?next=${encodeURIComponent(`${path}?run=1`)}`);
  });

  test.each([half, full])("a signed-in visitor goes through to the console, onboarded or not (%p)", (visitor) => {
    expect(RouteGuard.redirectFor("/console/runs", "", visitor)).toBeNull();
  });

  test.each(["/privacy", "/lessonsfoo", "/profiles", "/consolefoo"])("%s is not guarded", (path) => {
    expect(RouteGuard.redirectFor(path, "", out)).toBeNull();
  });
});
