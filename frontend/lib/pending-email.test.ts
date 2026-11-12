/**
 * Unit under test: `PendingEmail`, the address a sign-up code went to, kept in `sessionStorage`.
 *
 * Why: a refresh of the "Check your email" screen must still know where the code went. It is a convenience only, so with no
 * storage or storage that throws (private windows, blocked site data) nothing may throw and the screen offers to start again.
 *
 * Use cases:
 * - a saved address is read back (trimmed) and can be cleared
 * - a blank address clears what was saved
 * - with no storage, or storage that throws on any call, nothing throws and nothing is found
 */
import { describe, expect, test } from "bun:test";

import { PendingEmail, type EmailStorage } from "./pending-email";

function memory(): EmailStorage {
  const data = new Map<string, string>();
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v), removeItem: (k) => void data.delete(k) };
}

const broken: EmailStorage = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
  removeItem: () => {
    throw new Error("blocked");
  },
};

describe("PendingEmail", () => {
  test("a saved address is read back trimmed and can be cleared", () => {
    const store = new PendingEmail(memory());
    store.save("  Ada@Example.com ");

    expect(store.peek()).toBe("Ada@Example.com");
    store.clear();
    expect(store.peek()).toBeNull();
  });

  test("a blank address clears what was saved", () => {
    const store = new PendingEmail(memory());
    store.save("ada@example.com");
    store.save("   ");

    expect(store.peek()).toBeNull();
  });

  test("with no storage, or storage that throws, nothing throws and nothing is found", () => {
    for (const store of [new PendingEmail(undefined), new PendingEmail(broken)]) {
      expect(() => store.save("ada@example.com")).not.toThrow();
      expect(store.peek()).toBeNull();
      expect(() => store.clear()).not.toThrow();
    }
  });
});
