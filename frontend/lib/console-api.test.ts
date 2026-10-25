/**
 * Unit under test: `ConsoleApi`, the typed calls to the staff-only console endpoints.
 *
 * Why: a wrong path, method or body shape fails only at runtime, in front of a maintainer who is fixing something.
 * The paths have no trailing slash (the Next proxy depends on it), the console answers a stranger with a 404,
 * which also hides an expired session, and a list's cursor comes from the backend's absolute `next` link.
 *
 * Use cases:
 * - reads the overview, with the range only when one is given
 * - reads usage with only the filters that were given, and builds the link to download the same calls as a CSV
 * - lists runs with status and graph (one or several, as comma-separated parameters), a trimmed search, and a page
 * - reads one run and starts its retry or cancel
 * - lists and changes providers; lists, adds, changes, deletes and tests models
 * - reads the routing, saves a step with PUT, lists the profiles and previews one with POST
 * - reads and changes the lesson settings, lists learners (searched, paged) and the change log
 * - a 404 renews the session and is tried once more; at most one renewal a minute; any other failure is passed on
 * - extracts the cursor from a `next` link, and handles no link
 */
import { describe, expect, test } from "bun:test";

import { ApiError, type ApiClient, type RequestOptions } from "./api";
import { ConsoleApi } from "./console-api";

type Call = { path: string; options?: RequestOptions };

function fakeClient(outcomes: (unknown | Error)[] = [], refreshed = true) {
  const calls: Call[] = [];
  let refreshes = 0;
  const client = {
    request: async (path: string, options?: RequestOptions) => {
      calls.push({ path, options });
      const next = outcomes.shift();
      if (next instanceof Error) throw next;
      return next;
    },
    refreshSession: async () => {
      refreshes += 1;
      return refreshed;
    },
  } as unknown as ApiClient;
  let clock = 1_000_000;
  const api = new ConsoleApi(client, () => clock);
  return { api, calls, refreshes: () => refreshes, advance: (ms: number) => (clock += ms) };
}

const notFound = () => new ApiError(404, "not_found", "Not found.");

describe("ConsoleApi", () => {
  test("reads the overview, with the range only when one is given", async () => {
    const { api, calls } = fakeClient();

    await api.overview();
    await api.overview("30d");

    expect(calls.map((c) => c.path)).toEqual(["/console/overview", "/console/overview?range=30d"]);
    expect(calls[0].options).toEqual({ method: "GET" });
  });

  test("reads usage with only the filters that were given, and links the CSV of the same calls", async () => {
    const { api, calls } = fakeClient();

    await api.usage();
    await api.usage({ range: "today", provider: "groq", model: "openai/gpt-oss-120b", node: "", outcome: "retried" });

    expect(calls.map((c) => c.path)).toEqual([
      "/console/usage",
      "/console/usage?range=today&provider=groq&model=openai%2Fgpt-oss-120b&outcome=retried",
    ]);
    expect(api.usageExportUrl()).toBe("/api/console/usage/export.csv");
    expect(api.usageExportUrl({ range: "30d", node: "page.generate" })).toBe(
      "/api/console/usage/export.csv?range=30d&node=page.generate",
    );
  });

  test("lists runs with comma-separated filters, a trimmed search and a page", async () => {
    const { api, calls } = fakeClient();

    await api.runs();
    await api.runs({ status: ["failed", "running"], graph: "flow", q: "  binary ", cursor: "abc", pageSize: 50 });
    await api.runs({ status: "", graph: [], q: "   " });

    expect(calls.map((c) => c.path)).toEqual([
      "/console/runs",
      "/console/runs?status=failed%2Crunning&graph=flow&q=binary&cursor=abc&page_size=50",
      "/console/runs",
    ]);
  });

  test("reads one run and starts its retry or cancel", async () => {
    const { api, calls } = fakeClient();

    await api.run("r1");
    await api.retryRun("r1");
    await api.cancelRun("r1");

    expect(calls).toEqual([
      { path: "/console/runs/r1", options: { method: "GET" } },
      { path: "/console/runs/r1/retry", options: { method: "POST" } },
      { path: "/console/runs/r1/cancel", options: { method: "POST" } },
    ]);
  });

  test("lists and changes providers", async () => {
    const { api, calls } = fakeClient();

    await api.providers();
    await api.providers({ cursor: "c1" });
    await api.updateProvider("groq", { rpm_limit: null, enabled: false });

    expect(calls).toEqual([
      { path: "/console/providers", options: { method: "GET" } },
      { path: "/console/providers?cursor=c1", options: { method: "GET" } },
      { path: "/console/providers/groq", options: { method: "PATCH", body: { rpm_limit: null, enabled: false } } },
    ]);
  });

  test("lists, adds, changes, deletes and tests models", async () => {
    const { api, calls } = fakeClient();

    await api.models({ pageSize: 100 });
    await api.addModel({ provider: "groq", name: "openai/gpt-oss-20b", context_window: 131072 });
    await api.updateModel(7, { label: "GPT-OSS 20B", enabled: false });
    await api.deleteModel(7);
    await api.probeModel(7);

    expect(calls).toEqual([
      { path: "/console/models?page_size=100", options: { method: "GET" } },
      {
        path: "/console/models",
        options: { method: "POST", body: { provider: "groq", name: "openai/gpt-oss-20b", context_window: 131072 } },
      },
      { path: "/console/models/7", options: { method: "PATCH", body: { label: "GPT-OSS 20B", enabled: false } } },
      { path: "/console/models/7", options: { method: "DELETE" } },
      { path: "/console/models/7/probe", options: { method: "POST" } },
    ]);
  });

  test("reads the routing, saves a step with PUT, lists the profiles and previews one with POST", async () => {
    const { api, calls } = fakeClient();
    const routing = {
      enabled: true,
      reasoning_effort: "low" as const,
      max_attempts: 2,
      timeout_s: 60,
      bindings: [{ model: 3 }, { model: 4, max_retries: 0, overrides: { reasoning_effort: "high" as const } }],
    };

    await api.routing();
    await api.saveNode("lesson.plan", routing);
    await api.profiles();
    await api.previewProfile("cheap");

    expect(calls).toEqual([
      { path: "/console/nodes", options: { method: "GET" } },
      { path: "/console/nodes/lesson.plan", options: { method: "PUT", body: routing } },
      { path: "/console/profiles", options: { method: "GET" } },
      { path: "/console/profiles/cheap/preview", options: { method: "POST" } },
    ]);
  });

  test("reads and changes the lesson settings", async () => {
    const { api, calls } = fakeClient();

    await api.flowSettings();
    await api.updateFlowSettings({ diagnostic_questions_per_band: 3, media_sources: ["wikimedia"] });

    expect(calls).toEqual([
      { path: "/console/flow-settings", options: { method: "GET" } },
      {
        path: "/console/flow-settings",
        options: { method: "PATCH", body: { diagnostic_questions_per_band: 3, media_sources: ["wikimedia"] } },
      },
    ]);
  });

  test("lists learners (searched, paged) and the change log", async () => {
    const { api, calls } = fakeClient();

    await api.learners();
    await api.learners({ q: " ada ", cursor: "x" });
    await api.audit({ pageSize: 10 });

    expect(calls.map((c) => c.path)).toEqual([
      "/console/learners",
      "/console/learners?q=ada&cursor=x",
      "/console/audit?page_size=10",
    ]);
  });
});

describe("ConsoleApi and a 404", () => {
  test("renews the session and tries once more", async () => {
    const { api, calls, refreshes } = fakeClient([notFound(), { range: "7d" }]);

    const result = await api.overview();

    expect(result).toEqual({ range: "7d" } as never);
    expect(calls.map((c) => c.path)).toEqual(["/console/overview", "/console/overview"]);
    expect(refreshes()).toBe(1);
  });

  test("retries a write too: a 404 from the console means it did nothing", async () => {
    const { api, calls } = fakeClient([notFound(), { run_id: "n", lesson_id: "l" }]);

    await api.retryRun("r1");

    expect(calls.map((c) => `${c.options?.method} ${c.path}`)).toEqual([
      "POST /console/runs/r1/retry",
      "POST /console/runs/r1/retry",
    ]);
  });

  test("gives the 404 back when the session could not be renewed", async () => {
    const { api, calls } = fakeClient([notFound()], false);

    await expect(api.run("gone")).rejects.toMatchObject({ status: 404 });
    expect(calls).toHaveLength(1);
  });

  test("gives the 404 back when it comes again after the renewal", async () => {
    const { api, calls } = fakeClient([notFound(), notFound()]);

    await expect(api.run("gone")).rejects.toMatchObject({ status: 404 });
    expect(calls).toHaveLength(2);
  });

  test("renews the session at most once a minute", async () => {
    const { api, refreshes, advance } = fakeClient(Array.from({ length: 6 }, notFound));

    await api.run("a").catch(() => undefined); // renews, retries, 404 again
    await api.run("b").catch(() => undefined); // within the minute: no second renewal
    expect(refreshes()).toBe(1);

    advance(61_000);
    await api.run("c").catch(() => undefined);
    expect(refreshes()).toBe(2);
  });

  test("passes on every other failure without renewing", async () => {
    const conflict = new ApiError(409, "model_in_use", "In use.", {}, { nodes: ["lesson.plan"] });
    const { api, calls, refreshes } = fakeClient([conflict]);

    await expect(api.deleteModel(3)).rejects.toMatchObject({ status: 409, extra: { nodes: ["lesson.plan"] } });
    expect(calls).toHaveLength(1);
    expect(refreshes()).toBe(0);
  });
});

describe("ConsoleApi.cursorOf", () => {
  test("extracts the cursor from a next link, and handles none", () => {
    expect(ConsoleApi.cursorOf("http://backend:8000/api/console/runs?cursor=cD0yMDI2&page_size=2")).toBe("cD0yMDI2");
    expect(ConsoleApi.cursorOf(null)).toBeNull();
    expect(ConsoleApi.cursorOf("http://x/api/console/runs")).toBeNull();
  });
});
