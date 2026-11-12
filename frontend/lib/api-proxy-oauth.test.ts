/**
 * Unit under test: the `/api` proxy route handler (`app/api/[...path]/route.ts`) as the sign-in with a provider uses it.
 *
 * Why: the sign-in dance is the first thing behind the proxy that answers with a redirect and with several cookies at once. If
 * the proxy followed the redirect itself, dropped a `Set-Cookie`, or merged two of them into one header, a person would be sent
 * to the wrong place or arrive without the session (or without the signed cookie the last step needs). The same-origin proxy
 * must hand the browser exactly what Django said, and must forward the cookies the browser sent.
 *
 * Use cases:
 * - a `302` from Django reaches the browser as a `302` with its `Location`, unfollowed
 * - every `Set-Cookie` of the answer reaches the browser, each as its own header, attributes intact (path, HttpOnly, SameSite)
 * - the cookies and the query string of the browser's request are forwarded to Django unchanged, on the same path
 * - a callback with the provider's `code` and `state` in the query is forwarded whole
 */
import { afterEach, describe, expect, test } from "bun:test";

import { GET } from "../app/api/[...path]/route";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function browserRequest(url: string, headers: Record<string, string> = {}) {
  const request = new Request(url, { headers });
  return Object.assign(request, { nextUrl: new URL(url) }) as never;
}

function stubDjango(answer: Response) {
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} });
    return answer;
  }) as typeof fetch;
  return calls;
}

const ctx = (...path: string[]) => ({ params: Promise.resolve({ path }) }) as never;

describe("the proxy and a redirecting, cookie-setting answer", () => {
  test("a 302 reaches the browser unfollowed, with its Location", async () => {
    const calls = stubDjango(new Response(null, { status: 302, headers: { Location: "/auth/finish?next=%2Fquizzes" } }));

    const reply = await GET(browserRequest("http://localhost:3000/api/auth/oauth/google/callback?code=c&state=s"), ctx("auth", "oauth", "google", "callback"));

    expect(reply.status).toBe(302);
    expect(reply.headers.get("location")).toBe("/auth/finish?next=%2Fquizzes");
    expect((calls[0].init as { redirect?: string }).redirect).toBe("manual");
  });

  test("every Set-Cookie arrives as its own header with its attributes", async () => {
    const answer = new Response(null, { status: 302, headers: { Location: "/auth" } });
    answer.headers.append("Set-Cookie", "lc_access=jwt-a; HttpOnly; Path=/; SameSite=Lax");
    answer.headers.append("Set-Cookie", "lc_refresh=jwt-r; HttpOnly; Path=/api/auth; SameSite=Lax");
    answer.headers.append("Set-Cookie", "lc_oauth=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/api/auth/oauth; SameSite=Lax");
    stubDjango(answer);

    const reply = await GET(browserRequest("http://localhost:3000/api/auth/oauth/google/callback"), ctx("auth", "oauth", "google", "callback"));

    const cookies = reply.headers.getSetCookie();
    expect(cookies).toHaveLength(3);
    expect(cookies[0]).toContain("lc_access=jwt-a");
    expect(cookies[1]).toContain("Path=/api/auth");
    expect(cookies[2]).toContain("Max-Age=0");
    expect(cookies.every((cookie) => cookie.includes("SameSite=Lax"))).toBe(true);
  });

  test("the browser's cookies and the whole query go to Django on the same path", async () => {
    const calls = stubDjango(new Response(null, { status: 302, headers: { Location: "/auth" } }));

    await GET(
      browserRequest("http://localhost:3000/api/auth/oauth/google/callback?code=4%2F0AX&state=abc&scope=openid+email", { cookie: "lc_oauth=signed-ticket; csrftoken=t" }),
      ctx("auth", "oauth", "google", "callback"),
    );

    const url = new URL(calls[0].url);
    expect(url.pathname).toBe("/api/auth/oauth/google/callback");
    expect(url.search).toBe("?code=4%2F0AX&state=abc&scope=openid+email");
    expect(new Headers(calls[0].init.headers).get("cookie")).toBe("lc_oauth=signed-ticket; csrftoken=t");
  });
});
