/**
 * Unit under test: the `matcher` of `proxy.ts` against the pages of `app/`.
 *
 * Why: `proxy.ts` only runs for the paths its matcher lists, so a signed-in page left off it is reachable by a signed-out
 * visitor (and by a learner who has not finished the setup), which the route guard exists to stop. The matcher is a literal
 * Next reads without running our code, so it cannot be built from `RouteGuard.PROTECTED`; this test is what keeps the two
 * and the folder of pages in step. `/quizzes` was once missing and nobody noticed.
 *
 * Use cases:
 * - every page of `app/` that is not public is matched by the proxy (including the sub-pages under a protected prefix)
 * - every protected prefix of `RouteGuard` is matched
 * - the public pages (the landing page, sign-in, the legal pages and contact) are the only ones left out
 */
import { describe, expect, test } from "bun:test";
import { readdirSync } from "node:fs";
import { join } from "node:path";

import { config } from "../proxy";
import { RouteGuard } from "./route-guard";

const PUBLIC = new Set(["/", "/auth", "/privacy", "/terms", "/contact"]);
const APP = join(import.meta.dir, "..", "app");

/** The URL path of every page under `app/`: route groups vanish and a dynamic segment becomes a value. */
function pages(dir = APP, base = ""): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isFile() && entry.name === "page.tsx") found.push(base || "/");
    if (!entry.isDirectory() || entry.name === "api") continue;
    const segment = entry.name.startsWith("(") ? "" : entry.name.startsWith("[") ? "/x" : `/${entry.name}`;
    found.push(...pages(join(dir, entry.name), base + segment));
  }
  return found;
}

/** Whether Next would run the proxy for `path`: `/a/:path*` is `/a` and everything under it. */
function matched(path: string): boolean {
  return config.matcher.some((pattern) => (pattern.endsWith("/:path*") ? path === pattern.slice(0, -7) || path.startsWith(`${pattern.slice(0, -7)}/`) : path === pattern));
}

describe("the proxy matcher", () => {
  test("covers every page of the app that is not public", () => {
    const missed = pages().filter((path) => !PUBLIC.has(path) && !matched(path));

    expect(missed).toEqual([]);
  });

  test("covers every protected prefix", () => {
    for (const prefix of RouteGuard.PROTECTED) expect(matched(prefix)).toBe(true);
  });

  test("leaves out only the public pages", () => {
    const left = pages().filter((path) => !matched(path));

    expect(left.sort()).toEqual([...PUBLIC].filter((path) => path !== "/" && path !== "/auth").sort());
  });

  test("the search helper sees the pages it should", () => {
    expect(pages()).toContain("/quizzes/x");
    expect(pages()).toContain("/wallet/history");
    expect(pages()).toContain("/console/audit");
  });
});
