/**
 * Unit under test: `BuyReturn`, where a learner who has bought is sent back to.
 *
 * Why: most people come to the shop because they could not afford something, and after buying they want to be back on it,
 * not on a list. The last page of the app they were on is remembered for the tab only (it is tracked from the app's own page
 * changes: the browser's referrer does not change when the app moves between pages without a reload), and only a path of
 * this site is ever kept, so the page can never be made to send anyone elsewhere.
 *
 * Use cases:
 * - a page of the app is remembered with its query, and the latest one wins
 * - the shop's own pages (buy, wallet, streak), sign-in and setup, and anything that is not a path of this site are not
 *   remembered, so going to the shop does not forget where the learner started
 * - recalling gives the remembered path, else the lessons; something that is not a path of this site is never given
 * - a browser that will not store works, and gives the lessons
 */
import { describe, expect, test } from "bun:test";

import { BuyReturn } from "./buy-return";

class Store {
  values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

describe("visiting", () => {
  test("a page is kept with its query, and the latest wins", () => {
    const store = new Store();

    BuyReturn.visit("/quizzes/new", store);
    BuyReturn.visit("/lessons/abc?tab=test", store);

    expect(BuyReturn.recall(store)).toBe("/lessons/abc?tab=test");
  });

  test.each(["/buy", "/buy/return?order=1", "/wallet", "/wallet/history", "/streak", "/auth?next=%2Fbuy", "/onboarding", "https://evil.example/lessons/1", "//evil.example/x", "", "lessons"])(
    "%p is not kept",
    (path) => {
      const store = new Store();
      BuyReturn.visit(path, store);

      expect(BuyReturn.recall(store)).toBe("/lessons");
    },
  );

  test("going to the shop does not forget where the learner started", () => {
    const store = new Store();
    BuyReturn.visit("/quizzes/new", store);

    BuyReturn.visit("/buy", store);

    expect(BuyReturn.recall(store)).toBe("/quizzes/new");
  });

  test("look-alike prefixes are pages of the app", () => {
    const store = new Store();

    BuyReturn.visit("/buyers-guide", store);

    expect(BuyReturn.recall(store)).toBe("/buyers-guide");
  });
});

describe("recalling", () => {
  test("never gives anything that is not a path of this site", () => {
    const store = new Store();
    store.setItem(BuyReturn.KEY, "https://evil.example");
    expect(BuyReturn.recall(store)).toBe("/lessons");
    store.setItem(BuyReturn.KEY, "//evil.example/x");
    expect(BuyReturn.recall(store)).toBe("/lessons");
  });

  test("a browser that will not store works and gives the lessons", () => {
    const refusing = {
      getItem: () => {
        throw new Error("no");
      },
      setItem: () => {
        throw new Error("no");
      },
    };

    BuyReturn.visit("/lessons/1", refusing);

    expect(BuyReturn.recall(refusing)).toBe("/lessons");
    expect(BuyReturn.recall(null)).toBe("/lessons");
  });
});
