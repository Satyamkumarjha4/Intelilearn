/**
 * Unit under test: `ApiClient`, the browser's only way to call the Django API through the same-origin proxy.
 *
 * Why: every screen depends on it. A missing CSRF header makes every write fail with 403, a broken refresh signs
 * users out every 30 minutes, and a refresh on auth endpoints would loop or hide a real "wrong password".
 *
 * Use cases:
 * - sends JSON with same-origin credentials and parses the JSON reply
 * - returns undefined for 204 No Content
 * - adds the CSRF header to unsafe methods only, fetching the csrftoken cookie first when it is missing
 * - on a 401, refreshes the session once and retries the request
 * - never refreshes for the auth endpoints themselves
 * - shares one refresh between concurrent 401s
 * - turns an error reply into an ApiError with status, code, message and field errors
 * - falls back to a generic ApiError when the error body is not JSON
 */
import { describe, expect, test } from "bun:test";

import { ApiClient, ApiError } from "./api";

type Call = { url: string; init?: RequestInit };

function json(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A fake fetch that replies from a script, in order, and records every call. */
function fakeFetch(...replies: Response[]) {
  const calls: Call[] = [];
  const fetcher = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const reply = replies.shift();
    if (!reply) throw new Error(`unexpected request to ${url}`);
    return reply;
  };
  return { fetcher, calls };
}

const withToken = () => "token-123";

/** The ApiError a request rejects with (fails the test if it resolves or rejects with anything else). */
async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(() => null, (e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

function header(call: Call, name: string): string | undefined {
  return (call.init?.headers as Record<string, string> | undefined)?.[name];
}

describe("ApiClient", () => {
  test("sends JSON with same-origin credentials and parses the reply", async () => {
    const { fetcher, calls } = fakeFetch(json(200, { id: 1 }));
    const client = new ApiClient(fetcher, withToken);

    const result = await client.request<{ id: number }>("/profile", { method: "PUT", body: { goal: "exam_prep" } });

    expect(result).toEqual({ id: 1 });
    expect(calls[0].url).toBe("/api/profile");
    expect(calls[0].init?.credentials).toBe("same-origin");
    expect(calls[0].init?.body).toBe(JSON.stringify({ goal: "exam_prep" }));
    expect(header(calls[0], "Content-Type")).toBe("application/json");
  });

  test("returns undefined for 204 No Content", async () => {
    const { fetcher } = fakeFetch(new Response(null, { status: 204 }));

    expect(await new ApiClient(fetcher, withToken).request("/auth/logout", { method: "POST" })).toBeUndefined();
  });

  test("adds the CSRF header to unsafe methods only", async () => {
    const { fetcher, calls } = fakeFetch(json(200, {}), json(200, {}));
    const client = new ApiClient(fetcher, withToken);

    await client.request("/profile");
    await client.request("/profile", { method: "PATCH", body: {} });

    expect(header(calls[0], "X-CSRFToken")).toBeUndefined();
    expect(header(calls[1], "X-CSRFToken")).toBe("token-123");
  });

  test("fetches the csrftoken cookie first when it is missing", async () => {
    let cookie: string | null = null;
    const { fetcher, calls } = fakeFetch(new Response(null, { status: 204 }), json(200, {}));
    const setCookieOnCsrf = async (url: string, init?: RequestInit) => {
      if (url === "/api/auth/csrf") cookie = "fresh-token";
      return fetcher(url, init);
    };

    await new ApiClient(setCookieOnCsrf, () => cookie).request("/profile", { method: "POST", body: {} });

    expect(calls.map((c) => c.url)).toEqual(["/api/auth/csrf", "/api/profile"]);
    expect(header(calls[1], "X-CSRFToken")).toBe("fresh-token");
  });

  test("refreshes the session once on a 401 and retries", async () => {
    const { fetcher, calls } = fakeFetch(json(401, { detail: "expired" }), json(200, {}), json(200, { ok: true }));

    const result = await new ApiClient(fetcher, withToken).request("/profile");

    expect(result).toEqual({ ok: true });
    expect(calls.map((c) => c.url)).toEqual(["/api/profile", "/api/auth/refresh", "/api/profile"]);
  });

  test("never refreshes for the auth endpoints themselves", async () => {
    const wrongPassword = { detail: "Invalid email or password.", code: "invalid_credentials" };
    const { fetcher, calls } = fakeFetch(json(401, wrongPassword));
    const client = new ApiClient(fetcher, withToken);

    const error = await rejection(client.request("/auth/login", { method: "POST", body: {} }));

    expect(error.code).toBe("invalid_credentials");
    expect(calls.map((c) => c.url)).toEqual(["/api/auth/login"]);
  });

  test("shares one refresh between concurrent 401s", async () => {
    const { fetcher, calls } = fakeFetch(json(200, {}));
    const client = new ApiClient(fetcher, withToken);

    const [first, second] = await Promise.all([client.refreshSession(), client.refreshSession()]);

    expect(first && second).toBe(true);
    expect(calls).toHaveLength(1);
  });

  test("turns an error reply into an ApiError with its fields", async () => {
    const body = { detail: "Please correct the highlighted fields.", code: "invalid", fields: { email: ["Taken."] } };
    const { fetcher } = fakeFetch(json(400, body));
    const client = new ApiClient(fetcher, withToken);

    const error = await rejection(client.request("/auth/register", { method: "POST", body: {} }));

    expect([error.status, error.code, error.message]).toEqual([400, "invalid", body.detail]);
    expect(error.fields).toEqual({ email: ["Taken."] });
  });

  test("falls back to a generic ApiError when the body is not JSON", async () => {
    const { fetcher } = fakeFetch(new Response("<html>Bad gateway</html>", { status: 502 }));

    const error = await rejection(new ApiClient(fetcher, withToken).request("/profile"));

    expect([error.status, error.code, error.message]).toEqual([502, "error", "Request failed (502)"]);
  });
});
