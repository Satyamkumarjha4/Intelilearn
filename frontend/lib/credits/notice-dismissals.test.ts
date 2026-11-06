/**
 * Unit under test: `NoticeDismissals`, "not now" for a notice about credits running out (credits plan T27).
 *
 * Why: a banner that cannot be put away is nagging, and one that is gone for good hides credits that are still about to
 * run out. So a dismissal lasts the day, in this browser, and the next day the notice is back. A browser that will not
 * store must not break the page.
 *
 * Use cases:
 * - a dismissed notice is hidden the same day, and the others stay
 * - the next day it is back
 * - a dismissal survives a reload (a new object on the same storage)
 * - a stored value that is damaged or of the wrong kind is ignored
 * - a browser that refuses to store still hides it for this visit; no storage at all does too
 * - dismissing twice stores it once
 */
import { describe, expect, test } from "bun:test";

import { NoticeDismissals } from "./notice-dismissals";
import type { Notice } from "./types";

const notice = (id: string): Notice => ({ id, expires_on: "2026-11-08", days_left: 3, credits: 5, text: "5 credits will run out." });

class MemoryStore {
  values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

describe("a dismissal", () => {
  test("hides that notice for the day and no other", () => {
    const dismissals = new NoticeDismissals(new MemoryStore(), () => "2026-11-05");

    dismissals.dismiss("expiry-a");

    expect(dismissals.visible([notice("expiry-a"), notice("expiry-b")]).map((n) => n.id)).toEqual(["expiry-b"]);
    expect(dismissals.isDismissed("expiry-a")).toBe(true);
  });

  test("is over the next day", () => {
    const store = new MemoryStore();
    new NoticeDismissals(store, () => "2026-11-05").dismiss("expiry-a");

    expect(new NoticeDismissals(store, () => "2026-11-06").visible([notice("expiry-a")])).toHaveLength(1);
  });

  test("survives a reload", () => {
    const store = new MemoryStore();
    new NoticeDismissals(store, () => "2026-11-05").dismiss("expiry-a");

    expect(new NoticeDismissals(store, () => "2026-11-05").isDismissed("expiry-a")).toBe(true);
  });

  test("twice is stored once", () => {
    const store = new MemoryStore();
    const dismissals = new NoticeDismissals(store, () => "2026-11-05");

    dismissals.dismiss("expiry-a");
    dismissals.dismiss("expiry-a");

    expect(JSON.parse(store.getItem(NoticeDismissals.KEY)!).ids).toEqual(["expiry-a"]);
  });
});

describe("a browser that does not cooperate", () => {
  test.each(["not json", "42", '{"day":5,"ids":"x"}', "null"])("a stored %s is ignored", (value) => {
    const store = new MemoryStore();
    store.setItem(NoticeDismissals.KEY, value);

    expect(new NoticeDismissals(store, () => "2026-11-05").visible([notice("expiry-a")])).toHaveLength(1);
  });

  test("one that refuses to store still hides it for this visit", () => {
    const refusing = { getItem: () => null, setItem: () => { throw new Error("full"); } };
    const dismissals = new NoticeDismissals(refusing, () => "2026-11-05");

    dismissals.dismiss("expiry-a");

    expect(dismissals.isDismissed("expiry-a")).toBe(true);
  });

  test("no storage at all works the same", () => {
    const dismissals = new NoticeDismissals(null, () => "2026-11-05");

    dismissals.dismiss("expiry-a");

    expect(dismissals.visible([notice("expiry-a")])).toEqual([]);
  });

  test("the browser's own day is a date", () => {
    expect(NoticeDismissals.localDay()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
