/**
 * Unit under test: `SessionProbe`, how a page finds out whether anyone is signed in without making a request that fails.
 *
 * Why: the session marker cookie is httpOnly (the page cannot read it), and asking `/auth/me` while signed out is a 401
 * the browser prints in red, followed by a failed `/auth/refresh`, on every public page. The server can read the marker, so
 * a small same-origin endpoint tells the page. The marker is only a hint; the API still decides everything.
 *
 * Use cases:
 * - the server says signed in exactly when the marker cookie is there
 * - the page believes the endpoint's answer, signed in or not
 * - when the endpoint cannot be reached or answers nonsense, the page assumes signed in, so the real call decides and a
 *   hiccup never signs anyone out
 * - the question is never cached and carries the cookies of this site only
 */
import { describe, expect, test } from "bun:test";

import { SessionProbe } from "./session-probe";

const answer = (body: unknown, status = 200) => async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("SessionProbe.signedIn (server)", () => {
  test("is true only with the marker cookie", () => {
    expect(SessionProbe.signedIn({ has: (name) => name === "lc_session" })).toBe(true);
    expect(SessionProbe.signedIn({ has: () => false })).toBe(false);
    expect(SessionProbe.signedIn({ has: (name) => name === "lc_onboarded" })).toBe(false);
  });
});

describe("SessionProbe.ask (page)", () => {
  test("believes the endpoint", async () => {
    expect(await SessionProbe.ask(answer({ signedIn: true }))).toBe(true);
    expect(await SessionProbe.ask(answer({ signedIn: false }))).toBe(false);
  });

  test.each([
    ["an error status", answer({ detail: "x" }, 502)],
    ["a body that is not an answer", answer({ something: 1 })],
    ["a network failure", async () => Promise.reject(new Error("offline"))],
    ["a body that is not JSON", async () => new Response("<html>", { status: 200 })],
  ])("assumes signed in after %s, so the real call decides", async (_, fetcher) => {
    expect(await SessionProbe.ask(fetcher as never)).toBe(true);
  });

  test("asks the site's own endpoint, uncached, with this site's cookies", async () => {
    const seen: { url: string; init?: RequestInit }[] = [];

    await SessionProbe.ask(async (url, init) => {
      seen.push({ url: String(url), init });
      return new Response(JSON.stringify({ signedIn: false }));
    });

    expect(seen).toEqual([{ url: "/api/session", init: { credentials: "same-origin", cache: "no-store" } }]);
  });
});
