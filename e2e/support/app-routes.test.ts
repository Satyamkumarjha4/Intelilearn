/**
 * Unit under test: `AppRoutes`, which turns the files of the frontend's `app/` folder into the URL paths the e2e warm-up opens.
 *
 * Why: the warm-up is what lets several e2e workers share one `next dev` server. A route it missed is compiled in the
 * middle of someone else's test, which reloads their page and fails the run after a three-minute timeout.
 *
 * Use cases:
 * - a page file becomes its URL path, the home page is "/"
 * - route groups, written in parentheses, are not part of the path
 * - a dynamic segment gets an id to open it with
 * - only page files count (layouts, loading and route handlers compile with their page)
 * - the console is told apart, because only staff can open it
 * - the landing page and sign-in are the pages only a signed-out visit compiles
 * - the real app folder yields the pages the app is known to have
 */
import { describe, expect, test } from "bun:test";

import { AppRoutes } from "./app-routes";

describe("AppRoutes", () => {
  test("a page file becomes its path, and the home page is the root", () => {
    expect(AppRoutes.fromPageFiles(["page.tsx", "wallet/page.tsx", "wallet/history/page.tsx"])).toEqual([
      "/",
      "/wallet",
      "/wallet/history",
    ]);
  });

  test("route groups are not part of the path", () => {
    expect(AppRoutes.fromPageFiles(["console/(shell)/usage/page.tsx", "console/(shell)/page.tsx"])).toEqual([
      "/console",
      "/console/usage",
    ]);
  });

  test("a dynamic segment is opened with a sample id", () => {
    expect(AppRoutes.fromPageFiles(["lessons/[id]/page.tsx"])).toEqual([`/lessons/${AppRoutes.SAMPLE_ID}`]);
  });

  test("only page files count", () => {
    expect(AppRoutes.fromPageFiles(["layout.tsx", "lessons/loading.tsx", "api/auth/route.ts", "lessons/page.tsx"])).toEqual([
      "/lessons",
    ]);
  });

  test("the console is told apart from the learner pages", () => {
    expect(AppRoutes.isConsole("/console")).toBe(true);
    expect(AppRoutes.isConsole("/console/usage")).toBe(true);
    expect(AppRoutes.isConsole("/consoles")).toBe(false);
    expect(AppRoutes.isConsole("/lessons")).toBe(false);
  });

  test("the landing page and sign-in are the pages only a signed-out visit compiles", () => {
    expect(AppRoutes.isSignedOutOnly("/")).toBe(true);
    expect(AppRoutes.isSignedOutOnly("/auth")).toBe(true);
    expect(AppRoutes.isSignedOutOnly("/auth/verify")).toBe(true);
    expect(AppRoutes.isSignedOutOnly("/authors")).toBe(false);
    expect(AppRoutes.isSignedOutOnly("/lessons")).toBe(false);
    expect(AppRoutes.isSignedOutOnly("/privacy")).toBe(false);
  });

  test("the real app folder has the pages the app is known to have, dynamic ones included", () => {
    const routes = AppRoutes.discover();

    for (const path of ["/", "/auth", "/onboarding", "/lessons", "/lessons/new", "/quizzes", "/wallet", "/console", "/console/usage"]) {
      expect(routes).toContain(path);
    }
    expect(routes).toContain(`/lessons/${AppRoutes.SAMPLE_ID}`);
    expect(routes).toContain(`/quizzes/${AppRoutes.SAMPLE_ID}`);
  });
});
