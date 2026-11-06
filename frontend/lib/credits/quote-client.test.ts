/**
 * Unit under test: `QuoteClient`, which asks the server what something costs and remembers the answer a little while.
 *
 * Why: a form that shows its price changes it often (a count, a source, a number of sheets), and two labels often ask the
 * same question. Without a memory every keystroke and every label would be a request; with a bad one a price could be
 * stale. And a price that cannot be had must never block the action it is next to: the server decides on the click.
 *
 * Use cases:
 * - the same question is asked once; the order the hints were written in does not make it another question
 * - a different question is another request
 * - two labels asking the same thing at the same time share one request
 * - an answer is kept for 30 seconds and asked again after that; `clear` forgets everything
 * - `cached` gives a fresh answer without asking, and nothing otherwise
 * - a price that cannot be had is `null`, and is not remembered, so the next ask tries again
 * - a Retry is asked by the lesson and remembered the same way
 */
import { describe, expect, test } from "bun:test";

import { QuoteClient } from "./quote-client";
import type { Quote } from "./types";

const quote = (total: number): Quote => ({ action: "x", lines: [], due_now: total, later_lines: [], later: 0, total, exempt: false });

class FakeApi {
  calls: string[] = [];
  fail = false;
  async quote(action: string, size: Record<string, unknown>): Promise<Quote> {
    this.calls.push(`${action}:${JSON.stringify(size)}`);
    if (this.fail) throw new Error("down");
    return quote(Object.keys(size).length);
  }
  async retryQuote(lessonId: string): Promise<Quote> {
    this.calls.push(`retry:${lessonId}`);
    return quote(5);
  }
}

const setup = () => {
  const api = new FakeApi();
  const clock = { at: 1_000 };
  return { api, clock, client: new QuoteClient(api, () => clock.at) };
};

describe("asking", () => {
  test("the same question is asked once, however the hints were ordered", async () => {
    const { api, client } = setup();

    await client.quote({ action: "a", size: { x: 1, y: 2 } });
    await client.quote({ action: "a", size: { y: 2, x: 1 } });

    expect(api.calls).toHaveLength(1);
  });

  test("a different question is another request", async () => {
    const { api, client } = setup();

    await client.quote({ action: "a", size: { x: 1 } });
    await client.quote({ action: "a", size: { x: 2 } });
    await client.quote({ action: "b", size: { x: 1 } });

    expect(api.calls).toHaveLength(3);
  });

  test("two labels asking at the same time share one request", async () => {
    const { api, client } = setup();

    const [first, second] = await Promise.all([client.quote({ action: "a", size: {} }), client.quote({ action: "a", size: {} })]);

    expect(api.calls).toHaveLength(1);
    expect(first).toEqual(second);
  });
});

describe("remembering", () => {
  test("an answer is kept for 30 seconds and asked again after that", async () => {
    const { api, clock, client } = setup();
    await client.quote({ action: "a", size: {} });

    clock.at += QuoteClient.TTL_MS - 1;
    await client.quote({ action: "a", size: {} });
    expect(api.calls).toHaveLength(1);

    clock.at += 1;
    await client.quote({ action: "a", size: {} });
    expect(api.calls).toHaveLength(2);
  });

  test("clear forgets everything", async () => {
    const { api, client } = setup();
    await client.quote({ action: "a", size: {} });

    client.clear();
    await client.quote({ action: "a", size: {} });

    expect(api.calls).toHaveLength(2);
  });

  test("cached gives a fresh answer without asking, and nothing otherwise", async () => {
    const { api, client } = setup();
    expect(client.cached({ action: "a", size: {} })).toBeUndefined();

    await client.quote({ action: "a", size: {} });

    expect(client.cached({ action: "a", size: {} })?.total).toBe(0);
    expect(api.calls).toHaveLength(1);
  });
});

describe("a price that cannot be had", () => {
  test("is null, is not remembered, and is tried again next time", async () => {
    const { api, client } = setup();
    api.fail = true;

    expect(await client.quote({ action: "a", size: {} })).toBeNull();

    api.fail = false;
    expect((await client.quote({ action: "a", size: {} }))?.total).toBe(0);
    expect(api.calls).toHaveLength(2);
  });
});

describe("a retry", () => {
  test("is asked by the lesson and remembered", async () => {
    const { api, client } = setup();

    await client.retry("lesson-1");
    await client.retry("lesson-1");
    await client.retry("lesson-2");

    expect(api.calls).toEqual(["retry:lesson-1", "retry:lesson-2"]);
  });
});
