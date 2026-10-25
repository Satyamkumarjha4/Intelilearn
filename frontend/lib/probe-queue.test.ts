/**
 * Unit under test: `ProbeQueue`, which runs "Test all models" a couple at a time and reports each result as it arrives.
 *
 * Why: a test makes real calls to a provider and can take up to twenty seconds. Running every model at once would hit
 * the providers' rate limits (and the console's own throttle) and make the tests fail for the wrong reason; running them
 * one by one makes the staff wait for the slowest. Two at a time, with each row updating when its result comes, is the
 * compromise, and a model whose test cannot even be sent must not stop the rest.
 *
 * Use cases:
 * - runs at most two tests at the same time, and starts the next as soon as one finishes
 * - reports a model when its test starts and again with its result
 * - a test that throws is reported as a failed result and the queue goes on
 * - an empty list finishes at once
 * - stopping lets the running tests finish but starts no more
 */
import { describe, expect, test } from "bun:test";

import { ProbeQueue } from "./probe-queue";
import type { ProbeResult } from "./types";

const ok = (latency = 1): ProbeResult => ({ ok: true, latency_s: latency, error: null, checks: [] });

/** A probe the test settles by hand, to see what runs while others are pending. */
function manual() {
  const pending = new Map<number, (result: ProbeResult | Error) => void>();
  let running = 0;
  let peak = 0;
  const started: number[] = [];
  const probe = (id: number) => {
    started.push(id);
    running += 1;
    peak = Math.max(peak, running);
    return new Promise<ProbeResult>((resolve, reject) => {
      pending.set(id, (value) => {
        running -= 1;
        if (value instanceof Error) reject(value);
        else resolve(value);
      });
    });
  };
  const settle = async (id: number, value: ProbeResult | Error = ok()) => {
    pending.get(id)!(value);
    await new Promise((resolve) => setTimeout(resolve, 0));
  };
  return { probe, settle, started, peak: () => peak };
}

describe("run", () => {
  test("never has more than two tests going, and starts the next when one ends", async () => {
    const fake = manual();
    const queue = new ProbeQueue(fake.probe);

    const done = queue.run([1, 2, 3, 4], {});
    await Promise.resolve();
    expect(fake.started).toEqual([1, 2]);

    await fake.settle(2);
    expect(fake.started).toEqual([1, 2, 3]);
    await fake.settle(1);
    expect(fake.started).toEqual([1, 2, 3, 4]);
    await fake.settle(3);
    await fake.settle(4);
    await done;

    expect(fake.peak()).toBe(2);
  });

  test("the limit is a parameter", async () => {
    const fake = manual();
    const done = new ProbeQueue(fake.probe, 3).run([1, 2, 3, 4], {});
    await Promise.resolve();

    expect(fake.started).toEqual([1, 2, 3]);
    for (const id of [1, 2, 3, 4]) await fake.settle(id);
    await done;
  });

  test("reports a model when its test starts and again with its result", async () => {
    const events: string[] = [];
    await new ProbeQueue(async () => ok(2)).run([7], {
      onStart: (id) => events.push(`start ${id}`),
      onResult: (id, result) => events.push(`result ${id} ${result.ok}`),
    });

    expect(events).toEqual(["start 7", "result 7 true"]);
  });

  test("a test that throws is a failed result, and the rest still run", async () => {
    const results: [number, ProbeResult][] = [];
    const probe = async (id: number) => {
      if (id === 2) throw new TypeError("fetch failed");
      return ok();
    };

    await new ProbeQueue(probe).run([1, 2, 3], { onResult: (id, result) => results.push([id, result]) });

    expect(results.map(([id]) => id).sort()).toEqual([1, 2, 3]);
    const failed = results.find(([id]) => id === 2)![1];
    expect(failed).toEqual({ ok: false, latency_s: null, error: "The test could not be sent. Check the connection and try again.", checks: [] });
  });

  test("an empty list finishes at once", async () => {
    await new ProbeQueue(async () => ok()).run([], {});
  });

  test("a model listed twice is tested once", async () => {
    const seen: number[] = [];
    await new ProbeQueue(async (id) => (seen.push(id), ok())).run([1, 1, 2], {});

    expect(seen).toEqual([1, 2]);
  });

  test("stopping lets the running tests finish but starts no more", async () => {
    const fake = manual();
    const signal = { stopped: false };
    const results: number[] = [];

    const done = new ProbeQueue(fake.probe).run([1, 2, 3, 4], { onResult: (id) => results.push(id) }, signal);
    await Promise.resolve();
    signal.stopped = true;
    await fake.settle(1);
    await fake.settle(2);
    await done;

    expect(fake.started).toEqual([1, 2]);
    expect(results.sort()).toEqual([1, 2]);
  });
});
