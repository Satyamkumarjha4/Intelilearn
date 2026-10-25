/**
 * Unit under test: `UnsavedGuard`, which decides whether a click on a link would leave a page with unsaved changes.
 *
 * Why: the routing and settings pages keep edits in the browser until Save. A click on the menu would drop them without
 * a word, but a guard that stops every click is worse: a link that opens in a new tab, one with a modifier key, one to
 * another site's address (the browser's own prompt handles those) and one that only changes this page's query must go
 * through untouched, or the page becomes impossible to use.
 *
 * Use cases:
 * - a plain click on a link to another page of the console is stopped, and its destination returned
 * - links that do not leave the page pass: same path, new tab, download, modifier keys, a non-primary button, another site
 * - a click that something else already handled passes
 * - an empty or unusable link passes
 */
import { describe, expect, test } from "bun:test";

import { UnsavedGuard, type ClickInfo } from "./unsaved-guard";

const here = { origin: "https://socra.test", pathname: "/console/routing" };
const click = (extra: Partial<ClickInfo> = {}): ClickInfo => ({ href: "https://socra.test/console/models", target: "", download: false, button: 0, modified: false, handled: false, ...extra });

describe("destination", () => {
  test("a plain click on a link to another page is stopped, with the page it goes to", () => {
    expect(UnsavedGuard.destination(click(), here)).toBe("/console/models");
    expect(UnsavedGuard.destination(click({ href: "https://socra.test/console/runs?status=failed#top" }), here)).toBe("/console/runs?status=failed#top");
  });

  test.each([
    ["the same page with another query", { href: "https://socra.test/console/routing?node=a.b" }],
    ["the same page", { href: "https://socra.test/console/routing" }],
    ["a new tab", { target: "_blank" }],
    ["a download", { download: true }],
    ["a modifier key", { modified: true }],
    ["the middle button", { button: 1 }],
    ["another site", { href: "https://example.com/console/models" }],
    ["a click something else handled", { handled: true }],
    ["no address", { href: null }],
    ["an address that is not a web address", { href: "mailto:a@b.c" }],
    ["an address that does not parse", { href: "http://" }],
  ])("%s passes", (_name, extra) => {
    expect(UnsavedGuard.destination(click(extra), here)).toBeNull();
  });

  test("a link for the same window (target _self) is stopped like any other", () => {
    expect(UnsavedGuard.destination(click({ target: "_self" }), here)).toBe("/console/models");
  });
});
