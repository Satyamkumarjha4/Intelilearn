/**
 * Unit under test: `ConsoleNav`, the console's sidebar entries and which one is current.
 *
 * Why: the sidebar is the only way around the console. A wrong "current" marker, a missing page, or a badge that says
 * "0" or "1043" would send a maintainer the wrong way or cry wolf.
 *
 * Use cases:
 * - three sections (Monitor, Configure, People) with the eight pages, in order, each with a path under /console
 * - the overview is current only on /console; the others are current on their page and below it
 * - a look-alike path ("/console/usagefoo") is not a page; a trailing slash does not matter
 * - a path finds its item
 * - a badge is hidden for zero or nothing, shows the count, and caps at 99+
 */
import { describe, expect, test } from "bun:test";

import { ConsoleNav } from "./console-nav";

describe("ConsoleNav", () => {
  test("has the three sections and eight pages", () => {
    expect(ConsoleNav.SECTIONS.map((s) => [s.label, s.items.map((i) => i.label)])).toEqual([
      ["Monitor", ["Overview", "Usage & cost", "Lesson runs"]],
      ["Configure", ["Models", "Model routing", "Lesson settings"]],
      ["People", ["Learners", "Change log"]],
    ]);
    expect(ConsoleNav.items().every((i) => i.href === "/console" || i.href.startsWith("/console/"))).toBe(true);
    expect(new Set(ConsoleNav.items().map((i) => i.href)).size).toBe(8);
  });

  test.each([
    ["/console", "/console", true],
    ["/console", "/console/usage", false],
    ["/console/usage", "/console/usage", true],
    ["/console/runs", "/console/runs/abc", true],
    ["/console/usage", "/console/usagefoo", false],
    ["/console/usage", "/console/usage/", true],
    ["/console", "/console/", true],
    ["/console/runs", "/console", false],
  ])("%s is current on %s: %p", (href, pathname, expected) => {
    expect(ConsoleNav.isCurrent(href, pathname)).toBe(expected);
  });

  test("finds the item of a path", () => {
    expect(ConsoleNav.itemFor("/console/routing")?.label).toBe("Model routing");
    expect(ConsoleNav.itemFor("/console")?.label).toBe("Overview");
    expect(ConsoleNav.itemFor("/lessons")).toBeUndefined();
  });

  test.each([
    [undefined, null],
    [0, null],
    [3, "3"],
    [99, "99"],
    [100, "99+"],
  ])("a badge of %p is %p", (count, expected) => {
    expect(ConsoleNav.badge(count)).toBe(expected);
  });
});
