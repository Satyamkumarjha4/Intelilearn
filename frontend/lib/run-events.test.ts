/**
 * Unit under test: `RunEventStream`, which follows a lesson run's Server-Sent Events in the browser.
 *
 * Why: it is how the page learns that it is the learner's turn to answer a quiz. A stream that stays open after the
 * run ends makes the browser reconnect forever; one that swallows a dropped connection leaves a spinner on a
 * lesson that stopped.
 *
 * Use cases:
 * - connects to the run's own events URL and delivers parsed events by name
 * - closes itself after each terminal event (awaiting_input, done, error, cancelled)
 * - keeps listening after progress events
 * - ignores a message that is not JSON
 * - reports an error and closes when the browser gives up on the connection
 * - does nothing on a transient error the browser will retry
 * - can be closed by the caller
 */
import { describe, expect, test } from "bun:test";

import { RunEventStream, type EventSourceLike } from "./run-events";
import type { RunEvent } from "./types";

class FakeSource implements EventSourceLike {
  readyState = 1;
  closed = false;
  onerror: ((event: Event) => void) | null = null;
  private listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(readonly url: string) {}

  addEventListener(name: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(name, listener);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  emit(name: string, data: unknown) {
    this.listeners.get(name)?.({ data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent);
  }
}

function open() {
  const events: RunEvent[] = [];
  let source!: FakeSource;
  const stream = new RunEventStream("run-1", (event) => events.push(event), (url) => (source = new FakeSource(url)));
  return { stream, events, source };
}

describe("RunEventStream", () => {
  test("connects to the run's events URL and delivers parsed events by name", () => {
    const { events, source } = open();

    source.emit("node", { node: "load_context", status: "running" });

    expect(source.url).toBe("/api/runs/run-1/events");
    expect(events).toEqual([{ name: "node", data: { node: "load_context", status: "running" } }]);
  });

  test.each(["awaiting_input", "done", "error", "cancelled"])("closes itself after %s", (name) => {
    const { events, source } = open();

    source.emit(name, { kind: "diagnostic" });

    expect(events.map((e) => e.name)).toEqual([name as RunEvent["name"]]);
    expect(source.closed).toBe(true);
  });

  test("keeps listening after progress events", () => {
    const { source } = open();

    source.emit("snapshot", { status: "running" });
    source.emit("node", { node: "a", status: "done" });
    source.emit("model", { node: "a", model: "m", kind: "retry", reason: "429" });
    source.emit("warning", { message: "careful" });

    expect(source.closed).toBe(false);
  });

  test("ignores a message that is not JSON", () => {
    const { events, source } = open();

    source.emit("node", "not json");

    expect(events).toEqual([]);
    expect(source.closed).toBe(false);
  });

  test("reports an error and closes when the browser gives up on the connection", () => {
    const { events, source } = open();
    source.readyState = 2;

    source.onerror?.(new Event("error"));

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ name: "error", data: { code: "connection" } });
    expect(source.closed).toBe(true);
  });

  test("does nothing on a transient error the browser will retry", () => {
    const { events, source } = open();
    source.readyState = 0; // CONNECTING: the browser is reconnecting

    source.onerror?.(new Event("error"));

    expect(events).toEqual([]);
    expect(source.closed).toBe(false);
  });

  test("can be closed by the caller", () => {
    const { stream, source } = open();

    stream.close();
    stream.close();

    expect(source.closed).toBe(true);
  });
});
