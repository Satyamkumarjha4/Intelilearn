/**
 * Unit under test: `PeopleQueries`, the cache entries of the Learners and Change log pages.
 *
 * Why: a key that ignores the search shows the old search's learners; an entry that cannot say where its next page
 * starts makes "Show more" repeat the first page or never appear; asking for 100 learners on every keystroke would
 * hammer the console's throttle.
 *
 * Use cases:
 * - the learners list is keyed by the trimmed search, so "" and "  " are one entry and another search is another
 * - the list asks for a page of 25 after the cursor it was given, with the search, and the next page's cursor comes
 *   from the reply's `next` link (none when it was the last page)
 * - the sample for the tiles is one fixed entry of the newest 100, whatever is searched
 * - the change log pages by cursor too, 50 entries at a time
 */
import { describe, expect, test } from "bun:test";

import type { ConsoleApi } from "./console-api";
import { PeopleQueries } from "./console-people-queries";

function fake() {
  const calls: [string, unknown][] = [];
  const page = (next: string | null) => ({ results: [{ id: "x" }], next, previous: null, summary: { total: 1 } });
  const api = {
    learners: async (arg: unknown) => (calls.push(["learners", arg]), page("http://backend/api/console/learners?cursor=abc")),
    audit: async (arg: unknown) => (calls.push(["audit", arg]), page(null)),
  } as unknown as ConsoleApi;
  return { calls, queries: new PeopleQueries(api) };
}

const key = (options: { queryKey: unknown }): unknown => options.queryKey;
const fetchPage = (options: unknown, pageParam: string | null) =>
  (options as { queryFn: (context: { pageParam: string | null }) => Promise<unknown> }).queryFn({ pageParam });
const nextParam = (options: unknown, last: unknown) => (options as { getNextPageParam: (last: unknown) => unknown }).getNextPageParam(last);

describe("PeopleQueries keys", () => {
  const { queries } = fake();

  test("are under console, and a search is its own entry", () => {
    expect(key(queries.learners(""))).toEqual(["console", "learners", "list", ""]);
    expect(key(queries.learners("  aditi "))).toEqual(["console", "learners", "list", "aditi"]);
    expect(key(queries.learners("  "))).toEqual(key(queries.learners("")));
    expect(key(queries.learnerSample())).toEqual(["console", "learners", "sample"]);
    expect(key(queries.audit())).toEqual(["console", "audit"]);
  });

  test("searching for 'sample' is not the sample", () => {
    expect(key(queries.learners("sample"))).not.toEqual(key(queries.learnerSample()));
  });
});

describe("PeopleQueries fetchers", () => {
  test("a learners page asks for 25 after the cursor, with the search", async () => {
    const { calls, queries } = fake();
    const options = queries.learners("aditi");

    await fetchPage(options, null);
    await fetchPage(options, "abc");

    expect(calls).toEqual([
      ["learners", { q: "aditi", cursor: null, pageSize: 25 }],
      ["learners", { q: "aditi", cursor: "abc", pageSize: 25 }],
    ]);
  });

  test("the next page starts at the cursor in the reply's next link, and there is none after the last", () => {
    const { queries } = fake();

    expect(nextParam(queries.learners(""), { next: "http://backend/api/console/learners?cursor=abc" })).toBe("abc");
    expect(nextParam(queries.learners(""), { next: null })).toBeUndefined();
    expect(nextParam(queries.audit(), { next: null })).toBeUndefined();
  });

  test("the sample is the newest 100 with no search", async () => {
    const { calls, queries } = fake();

    await (queries.learnerSample() as unknown as { queryFn: () => Promise<unknown> }).queryFn();

    expect(calls).toEqual([["learners", { pageSize: 100 }]]);
  });

  test("the change log asks for 50 after the cursor", async () => {
    const { calls, queries } = fake();

    await fetchPage(queries.audit(), "zz");

    expect(calls).toEqual([["audit", { cursor: "zz", pageSize: 50 }]]);
  });
});
