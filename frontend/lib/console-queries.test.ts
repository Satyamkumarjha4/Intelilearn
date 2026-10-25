/**
 * Unit under test: `ConsoleQueries` (the console pages' cache entries), `FailedRuns` (the sidebar badge) and
 * `ConsoleErrors` (404 means "not for you", and which failures are worth asking again).
 *
 * Why: a key that ignores a filter shows the old filter's numbers; a key that differs for "" and "not set" fetches twice;
 * a retry on a 404 delays the not-found page; a badge that counts old failures raises a false alarm.
 *
 * Use cases:
 * - each query is keyed under "console" and by what it was asked for; empty filters do not change the key
 * - the overview is polled every minute; lists stay fresh for minutes
 * - routing, profiles and the lesson settings are keyed under console too; the two that are edited on their page do not refetch on focus
 * - each fetcher calls the right API method with the right arguments, and returns the part the pages need
 * - the failed-runs count counts the last 24 hours only
 * - a 404 is "not found", other errors are not; 400, 401, 403 and 404 are not retried, other failures twice
 * - the console's query client refetches on focus, keeps data briefly fresh, and retries by the same rule
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import type { ConsoleApi } from "./console-api";
import { ConsoleErrors, ConsoleQueries, ConsoleQueryClient, FailedRuns } from "./console-queries";

function fake() {
  const calls: [string, unknown?][] = [];
  const reply = (name: string, value: unknown) => async (arg?: unknown) => {
    calls.push([name, arg]);
    return value;
  };
  const api = {
    overview: reply("overview", { range: "7d" }),
    usage: reply("usage", { kpis: {} }),
    providers: reply("providers", { results: [{ key: "groq" }] }),
    models: reply("models", { results: [{ id: 1 }] }),
    routing: reply("routing", { phases: [{ nodes: [{ key: "a" }, { key: "b" }] }, { nodes: [{ key: "c" }] }] }),
    profiles: reply("profiles", [{ name: "cheap" }]),
    flowSettings: reply("flowSettings", { final_test_min: 10 }),
    runs: reply("runs", {
      results: [
        { created_at: "2026-03-15T11:00:00Z" },
        { created_at: "2026-03-14T13:00:00Z" },
        { created_at: "2026-03-14T11:59:00Z" },
      ],
    }),
  } as unknown as ConsoleApi;
  return { calls, queries: new ConsoleQueries(api, () => Date.parse("2026-03-15T12:00:00Z")) };
}

/** A key as a plain value: its type is branded with the data it will hold, which `toEqual` would compare against. */
const key = (options: { queryKey: unknown }): unknown => options.queryKey;
const run = async (options: { queryFn?: unknown }) => (options.queryFn as () => Promise<unknown>)();

describe("ConsoleQueries keys", () => {
  const { queries } = fake();

  test("are under console and carry what was asked for", () => {
    expect(key(queries.overview("30d"))).toEqual(["console", "overview", "30d"]);
    expect(key(queries.overview("today"))).not.toEqual(queries.overview("30d").queryKey);
    expect(key(queries.usage({ range: "7d", provider: "groq" }))).toEqual(["console", "usage", { range: "7d", provider: "groq" }]);
    expect(key(queries.providers())).toEqual(["console", "providers"]);
    expect(key(queries.models())).toEqual(["console", "models"]);
    expect(key(queries.steps())).toEqual(["console", "steps"]);
    expect(key(queries.failedRuns())).toEqual(["console", "failed-runs"]);
    expect(key(queries.routing())).toEqual(["console", "routing"]);
    expect(key(queries.profiles())).toEqual(["console", "profiles"]);
    expect(key(queries.flowSettings())).toEqual(["console", "flow-settings"]);
  });

  test("empty filters are the same entry as missing ones", () => {
    expect(queries.usage({ range: "7d", provider: "", model: "", outcome: "" }).queryKey).toEqual(queries.usage({ range: "7d" }).queryKey);
    expect(queries.usage({ provider: "groq" }).queryKey).not.toEqual(queries.usage({ provider: "gemini" }).queryKey);
  });
});

describe("ConsoleQueries timing", () => {
  const { queries } = fake();

  test("the overview is polled each minute, the lists are fresh for five", () => {
    expect(queries.overview("7d").refetchInterval).toBe(60_000);
    expect(queries.failedRuns().refetchInterval).toBe(60_000);
    expect(queries.models().staleTime).toBe(300_000);
    expect(queries.providers().staleTime).toBe(300_000);
    expect(queries.steps().staleTime).toBe(300_000);
  });

  test("what is edited on a page does not refetch under the edits when the tab regains focus", () => {
    expect(queries.routing().refetchOnWindowFocus).toBe(false);
    expect(queries.flowSettings().refetchOnWindowFocus).toBe(false);
    expect(queries.profiles().staleTime).toBe(300_000);
  });

  test("usage is not polled", () => {
    expect(queries.usage({}).refetchInterval).toBeUndefined();
  });
});

describe("ConsoleQueries fetchers", () => {
  test("call the API with the arguments they were built with", async () => {
    const { queries, calls } = fake();

    await run(queries.overview("today"));
    await run(queries.usage({ range: "30d", node: "page.generate" }));

    expect(calls).toEqual([["overview", "today"], ["usage", { range: "30d", node: "page.generate" }]]);
  });

  test("lists return their rows, asking for a full page", async () => {
    const { queries, calls } = fake();

    expect(await run(queries.providers())).toEqual([{ key: "groq" }] as never);
    expect(await run(queries.models())).toEqual([{ id: 1 }] as never);
    expect(calls).toEqual([["providers", { pageSize: 100 }], ["models", { pageSize: 100 }]]);
  });

  test("routing, profiles and settings are what the API returns", async () => {
    const { queries, calls } = fake();

    expect(await run(queries.routing())).toEqual({ phases: [{ nodes: [{ key: "a" }, { key: "b" }] }, { nodes: [{ key: "c" }] }] } as never);
    expect(await run(queries.profiles())).toEqual([{ name: "cheap" }] as never);
    expect(await run(queries.flowSettings())).toEqual({ final_test_min: 10 } as never);
    expect(calls.map(([name]) => name)).toEqual(["routing", "profiles", "flowSettings"]);
  });

  test("steps are the node keys in lesson order", async () => {
    expect(await run(fake().queries.steps())).toEqual(["a", "b", "c"] as never);
  });

  test("failed runs counts the last day of the failed ones", async () => {
    const { queries, calls } = fake();

    expect(await run(queries.failedRuns())).toBe(2 as never); // 11:00 today and 13:00 yesterday; not 11:59 the day before
    expect(calls).toEqual([["runs", { status: "failed", pageSize: 100 }]]);
  });
});

describe("FailedRuns.countWithin", () => {
  const now = Date.parse("2026-03-15T12:00:00Z");

  test("counts runs from the last 24 hours, the boundary included", () => {
    const rows = [{ created_at: "2026-03-14T12:00:00Z" }, { created_at: "2026-03-14T11:59:59Z" }, { created_at: "2026-03-15T12:00:00Z" }];

    expect(FailedRuns.countWithin(rows, now)).toBe(2);
    expect(FailedRuns.countWithin(rows, now, 1)).toBe(1);
    expect(FailedRuns.countWithin([], now)).toBe(0);
  });
});

describe("ConsoleErrors", () => {
  const error = (status: number) => new ApiError(status, "x", "x");

  test("only a 404 ApiError is not found", () => {
    expect(ConsoleErrors.isNotFound(error(404))).toBe(true);
    expect(ConsoleErrors.isNotFound(error(500))).toBe(false);
    expect(ConsoleErrors.isNotFound(new Error("404"))).toBe(false);
    expect(ConsoleErrors.isNotFound(null)).toBe(false);
  });

  test.each([400, 401, 403, 404])("a %i is not asked again", (status) => {
    expect(ConsoleErrors.shouldRetry(0, error(status))).toBe(false);
  });

  test("other failures are asked again twice", () => {
    expect(ConsoleErrors.shouldRetry(0, error(502))).toBe(true);
    expect(ConsoleErrors.shouldRetry(1, new TypeError("network"))).toBe(true);
    expect(ConsoleErrors.shouldRetry(2, error(502))).toBe(false);
  });
});

describe("ConsoleQueryClient", () => {
  test("refetches on focus, keeps data fresh for a short while, and does not retry a refusal", () => {
    const client = ConsoleQueryClient.create();
    const defaults = client.getDefaultOptions().queries!;

    expect(defaults.refetchOnWindowFocus).toBe(true);
    expect(defaults.staleTime).toBe(ConsoleQueryClient.STALE_MS);
    const retry = defaults.retry as (count: number, error: unknown) => boolean;
    expect(retry(0, new ApiError(404, "not_found", "nope"))).toBe(false);
    expect(retry(1, new Error("boom"))).toBe(true);
    expect(retry(2, new Error("boom"))).toBe(false);
  });

  test("each call makes a separate client, so one visit's cache is not another's", () => {
    expect(ConsoleQueryClient.create()).not.toBe(ConsoleQueryClient.create());
  });
});
