/**
 * Unit under test: `ApiClient.observe`, which tells one listener about every request that fails.
 *
 * Why: too few credits (a 402) can come back from a dozen different screens, and each already writes its own words. One
 * place that hears about all of them can add what they share (a way to buy credits, a fresh balance) without every screen
 * having to remember to.
 *
 * Use cases:
 * - a listener hears each failed request, with the error and the path, and the caller still gets the error
 * - a request that works tells nobody
 * - a failure after the silent refresh is heard once, not for the 401 that was retried
 * - stopping an observer stops it, and the others carry on
 * - a listener that throws changes nothing for the caller
 */
import { describe, expect, test } from "bun:test";

import { ApiClient, ApiError } from "./api";

const json = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const client = (...replies: Response[]) => new ApiClient(async () => replies.shift() ?? json(200, {}), () => "token");

describe("observing failures", () => {
  test("a listener hears the error and the path, and the caller still gets the error", async () => {
    const api = client(json(402, { detail: "You need 3 credits.", code: "insufficient_credits", required: 3, available: 1 }));
    const heard: [number, string, string][] = [];
    api.observe((error, path) => heard.push([error.status, error.code, path]));

    const failure = await api.request("/lessons", { method: "POST", body: {} }).catch((e) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect(heard).toEqual([[402, "insufficient_credits", "/lessons"]]);
  });

  test("a request that works tells nobody", async () => {
    const api = client(json(200, { ok: true }));
    let heard = 0;
    api.observe(() => heard++);

    await api.request("/credits/balance");

    expect(heard).toBe(0);
  });

  test("a 401 that is retried after the refresh is not heard, only what comes of the retry", async () => {
    const api = client(json(401, { code: "not_authenticated" }), json(200, {}), json(402, { code: "insufficient_credits" }));
    const heard: number[] = [];
    api.observe((error) => heard.push(error.status));

    await api.request("/lessons", { method: "POST", body: {} }).catch(() => undefined);

    expect(heard).toEqual([402]);
  });

  test("stopping an observer stops it, and the others carry on", async () => {
    const api = client(json(500), json(500));
    const first: number[] = [];
    const second: number[] = [];
    const stop = api.observe((error) => first.push(error.status));
    api.observe((error) => second.push(error.status));

    await api.request("/a").catch(() => undefined);
    stop();
    await api.request("/b").catch(() => undefined);

    expect([first, second]).toEqual([[500], [500, 500]]);
  });

  test("a listener that throws changes nothing for the caller", async () => {
    const api = client(json(404, { detail: "Not found", code: "not_found" }));
    api.observe(() => {
      throw new Error("bug in the observer");
    });

    const failure = await api.request("/a").catch((e) => e);

    expect(failure).toMatchObject({ status: 404, code: "not_found" });
  });
});
