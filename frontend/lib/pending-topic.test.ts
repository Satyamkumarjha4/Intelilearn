/**
 * Unit under test: `PendingTopic`, the topic a visitor types into the landing page's call to action.
 *
 * Why: the visitor types a topic before they have an account. It has to survive the trip through sign-up so the next
 * screens can offer it, but it is only a convenience: a browser that blocks storage, or a blank box, must never stop
 * them from signing up.
 *
 * Use cases:
 * - a topic is kept trimmed, and cut to the length the lesson form allows
 * - a blank topic keeps nothing, and clears one typed earlier
 * - the topic is read back once and forgotten (`take`), and can be looked at without being forgotten (`peek`)
 * - with no storage, or storage that throws, saving and reading do nothing and do not fail
 */
import { describe, expect, test } from "bun:test";

import { PendingTopic, type TopicStorage } from "./pending-topic";

class MemoryStorage implements TopicStorage {
  readonly items = new Map<string, string>();
  getItem = (key: string) => this.items.get(key) ?? null;
  setItem = (key: string, value: string) => void this.items.set(key, value);
  removeItem = (key: string) => void this.items.delete(key);
}

const broken: TopicStorage = {
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

describe("PendingTopic", () => {
  test("a topic is kept trimmed and cut to the allowed length", () => {
    const storage = new MemoryStorage();
    const topic = new PendingTopic(storage, 10);

    topic.save("  Photosynthesis in plants  ");

    expect(storage.items.get("socra.pendingTopic")).toBe("Photosynth");
    expect(topic.peek()).toBe("Photosynth");
  });

  test("a blank topic keeps nothing and clears an earlier one", () => {
    const storage = new MemoryStorage();
    const topic = new PendingTopic(storage);
    topic.save("Ohm's law");
    topic.save("   ");

    expect(topic.peek()).toBeNull();
  });

  test("take reads the topic once, peek leaves it", () => {
    const topic = new PendingTopic(new MemoryStorage());
    topic.save("Recursion");

    expect(topic.peek()).toBe("Recursion");
    expect(topic.take()).toBe("Recursion");
    expect(topic.take()).toBeNull();
  });

  test("without storage, or with storage that throws, nothing fails", () => {
    for (const storage of [undefined, broken]) {
      const topic = new PendingTopic(storage);

      expect(() => topic.save("Recursion")).not.toThrow();
      expect(topic.peek()).toBeNull();
      expect(topic.take()).toBeNull();
    }
  });
});
