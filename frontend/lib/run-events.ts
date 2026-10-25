import type { RunEvent, RunEventName } from "@/lib/types";

/** The events after which a run segment is over and the page should refetch the lesson. */
export const TERMINAL_EVENTS: ReadonlySet<RunEventName> = new Set(["awaiting_input", "done", "error", "cancelled"]);

export const EVENT_NAMES: RunEventName[] = [
  "snapshot",
  "node",
  "model",
  "warning",
  "awaiting_input",
  "done",
  "error",
  "cancelled",
];

/** The slice of the browser's EventSource that the stream uses (so tests can supply a fake). */
export interface EventSourceLike {
  readyState: number;
  addEventListener(name: string, listener: (event: MessageEvent) => void): void;
  close(): void;
  onerror: ((event: Event) => void) | null;
}

export type EventSourceFactory = (url: string) => EventSourceLike;

const CLOSED = 2;

/**
 * Follows one run's Server-Sent Events. It closes itself after a terminal event: left open, the browser would
 * reconnect to the finished run again and again.
 */
export class RunEventStream {
  private source: EventSourceLike | null;

  constructor(
    runId: string,
    private readonly onEvent: (event: RunEvent) => void,
    factory: EventSourceFactory = (url) => new EventSource(url),
  ) {
    this.source = factory(`/api/runs/${runId}/events`);
    for (const name of EVENT_NAMES) {
      this.source.addEventListener(name, (message) => this.receive(name, message.data));
    }
    this.source.onerror = () => {
      // A dropped connection reconnects by itself; only a source the browser gave up on is an error.
      if (this.source?.readyState === CLOSED) {
        this.deliver({ name: "error", data: { message: "Lost the connection to the server.", code: "connection" } });
        this.close();
      }
    };
  }

  close(): void {
    this.source?.close();
    this.source = null;
  }

  private receive(name: RunEventName, text: string): void {
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      return; // not one of ours
    }
    this.deliver({ name, data } as RunEvent);
    if (TERMINAL_EVENTS.has(name)) this.close();
  }

  private deliver(event: RunEvent): void {
    this.onEvent(event);
  }
}
