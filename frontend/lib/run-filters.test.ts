/**
 * Unit under test: `RunFilters`, the filters and the selected run of the console's run list, as they live in the address.
 *
 * Why: staff share links to "the failed runs" or to one run, and the overview links into this page with a filter.
 * The address is untrusted input, and the run id in it goes straight into an API path, so anything that is not a
 * run id must be dropped, not sent.
 *
 * Use cases:
 * - reads the status tab, the job, the search and the run from the address, with defaults for what is missing
 * - drops values it does not know (a status, a job) and anything that is not a run id (a path trying to climb out)
 * - writes the address back leaving out the defaults, and the search trimmed
 * - turns the status tab into the statuses the API is asked for (running also covers queued)
 * - turns the filters into the API query, leaving the run out of it
 * - changes one filter and keeps the others, including the selected run
 * - recognises a whole run id typed or pasted into the search box (the API searches topics and learners, not ids)
 * - writes the Failed tab's count: nothing for none or not yet known, the number, and "100+" when there are more than
 *   one page
 */
import { describe, expect, test } from "bun:test";

import { RunFilters } from "./run-filters";

const RUN = "7f3a9c10-2b44-4a8e-9d11-0e5b7c1d2f33";

describe("parse", () => {
  test("reads every filter from the address", () => {
    const filters = RunFilters.parse(new URLSearchParams(`status=failed&job=flow&q=ohm&run=${RUN}`));

    expect(filters).toEqual({ status: "failed", job: "flow", q: "ohm", run: RUN });
  });

  test("uses the defaults for an empty address", () => {
    expect(RunFilters.parse(new URLSearchParams(""))).toEqual({ status: "all", job: "", q: "", run: null });
  });

  test("drops a status or a job it does not know", () => {
    const filters = RunFilters.parse(new URLSearchParams("status=exploded&job=everything"));

    expect(filters).toMatchObject({ status: "all", job: "" });
  });

  test.each(["../../providers", "7f3a", "7f3a9c10-2b44-4a8e-9d11-0e5b7c1d2f33/retry", "<script>"])("drops %p as a run id", (run) => {
    expect(RunFilters.parse(new URLSearchParams({ run })).run).toBeNull();
  });
});

describe("href", () => {
  test("leaves out the defaults", () => {
    expect(RunFilters.href("/console/runs", { status: "all", job: "", q: "", run: null })).toBe("/console/runs");
  });

  test("writes every filter that is set, with the search trimmed and encoded", () => {
    const href = RunFilters.href("/console/runs", { status: "running", job: "grade_test", q: " newton's laws ", run: RUN });

    expect(href).toBe(`/console/runs?status=running&job=grade_test&q=newton%27s+laws&run=${RUN}`);
  });

  test("leaves out a search of only spaces", () => {
    expect(RunFilters.href("/console/runs", { status: "all", job: "", q: "   ", run: null })).toBe("/console/runs");
  });

  test("reads back what it wrote", () => {
    const filters = { status: "succeeded", job: "runtime_repair", q: "ohm's law", run: RUN } as const;

    const href = RunFilters.href("/x", filters);

    expect(RunFilters.parse(new URL(href, "http://x").searchParams)).toEqual(filters);
  });
});

describe("query", () => {
  test.each([
    ["all", []],
    ["running", ["queued", "running"]],
    ["failed", ["failed"]],
    ["succeeded", ["succeeded"]],
  ] as const)("the %s tab asks for %p", (status, statuses) => {
    expect(RunFilters.query({ status, job: "", q: "", run: null }).status).toEqual([...statuses]);
  });

  test("passes the job and the trimmed search, and leaves the selected run out", () => {
    const query = RunFilters.query({ status: "failed", job: "flow", q: " ohm ", run: RUN });

    expect(query).toEqual({ status: ["failed"], graph: "flow", q: "ohm" });
  });
});

describe("change", () => {
  test("changes one filter and keeps the rest", () => {
    const before = { status: "failed", job: "flow", q: "ohm", run: RUN } as const;

    expect(RunFilters.change(before, { status: "all" })).toEqual({ ...before, status: "all" });
    expect(RunFilters.change(before, { run: null })).toEqual({ ...before, run: null });
  });
});

describe("run id in the search box", () => {
  test("finds a whole run id, whatever its case and the spaces around it", () => {
    expect(RunFilters.runIdIn(` ${RUN.toUpperCase()} `)).toBe(RUN.toUpperCase());
  });

  test.each(["", "ohm", "7f3a9c10", `${RUN} extra`, `../${RUN}`])("finds none in %p", (text) => {
    expect(RunFilters.runIdIn(text)).toBeNull();
  });
});

describe("failed count", () => {
  test.each([
    [null, false, "Failed"],
    [0, false, "Failed"],
    [3, false, "Failed · 3"],
    [100, true, "Failed · 100+"],
  ])("%p failed runs (more: %p) read %p", (count, more, label) => {
    expect(RunFilters.tabLabel("failed", count, more)).toBe(label);
  });

  test("leaves the other tabs' labels alone", () => {
    expect(RunFilters.tabLabel("running", 7, false)).toBe("Running");
  });
});

describe("tabs and jobs", () => {
  test("offer All, Running, Failed and Finished, and the four kinds of job", () => {
    expect(RunFilters.TABS.map((t) => t.label)).toEqual(["All", "Running", "Failed", "Finished"]);
    expect(RunFilters.JOBS.map((j) => j.label)).toEqual(["Lesson flow", "Study sheet", "Repair", "Grading"]);
  });
});
