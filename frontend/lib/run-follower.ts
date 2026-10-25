import { RunText } from "@/lib/run-text";
import { TERMINAL_EVENTS } from "@/lib/run-events";
import type { RunDetail, RunEvent } from "@/lib/types";

export interface FollowTimers {
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export type FollowOptions = {
  load: () => Promise<RunDetail>;
  onDetail: (detail: RunDetail) => void;
  onError?: (error: unknown) => void;
  /** Opens the run's event stream. It is not asked for a run that is not moving. */
  open: (onEvent: (event: RunEvent) => void) => { close(): void };
  timers?: FollowTimers;
};

const REAL_TIMERS: FollowTimers = {
  now: () => Date.now(),
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/**
 * Keeps one run's detail current while the run is moving. The events say *when* something changed and the console's
 * detail says *what* (the server owns the timings), so every event, and a slow beat in between so that a running
 * step's bar keeps growing, reloads the detail. The stream belongs to the learner whose run it is, so for anyone
 * else's run it is refused: the follower then asks on a faster beat. Reloads are spaced (the console is throttled),
 * and everything stops once a load shows the run is over.
 */
export class RunFollower {
  static readonly TICK_MS = 5000;
  static readonly POLL_MS = 3000;
  static readonly MIN_GAP_MS = 1000;

  private readonly timers: FollowTimers;
  private stream: { close(): void } | null = null;
  private timer: unknown = null;
  private polling = false;
  private stopped = false;
  private loading = false;
  private lastLoad = Number.NEGATIVE_INFINITY;

  constructor(private readonly options: FollowOptions) {
    this.timers = options.timers ?? REAL_TIMERS;
  }

  start(): void {
    void this.load();
  }

  stop(): void {
    this.stopped = true;
    this.release();
  }

  private async load(): Promise<void> {
    if (this.stopped) return;
    if (this.loading) return this.schedule(RunFollower.MIN_GAP_MS); // one load at a time; the next one picks it up
    this.loading = true;
    this.lastLoad = this.timers.now();
    try {
      const detail = await this.options.load();
      if (this.stopped) return;
      this.options.onDetail(detail);
      this.follow(detail);
    } catch (error) {
      if (this.stopped) return;
      this.options.onError?.(error);
      this.schedule(RunFollower.POLL_MS);
    } finally {
      this.loading = false;
    }
  }

  private follow(detail: RunDetail): void {
    if (!RunText.isActive(detail.status)) return this.release();
    if (!this.stream && !this.polling) this.stream = this.options.open((event) => this.receive(event));
    this.schedule(this.polling ? RunFollower.POLL_MS : RunFollower.TICK_MS);
  }

  private receive(event: RunEvent): void {
    if (this.stopped) return;
    const refused = event.name === "error" && event.data.code === "connection";
    const over = TERMINAL_EVENTS.has(event.name);
    if (refused || over) {
      // The stream has closed itself. The database may not have caught up with a closing event yet, so keep asking.
      this.stream = null;
      this.polling = true;
    }
    this.schedule(over && !refused ? 0 : RunFollower.MIN_GAP_MS - this.sinceLastLoad());
  }

  private sinceLastLoad(): number {
    return Math.min(this.timers.now() - this.lastLoad, RunFollower.MIN_GAP_MS);
  }

  private schedule(ms: number): void {
    if (this.stopped) return;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      void this.load();
    }, Math.max(0, ms));
  }

  private release(): void {
    this.stream?.close();
    this.stream = null;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
  }
}
