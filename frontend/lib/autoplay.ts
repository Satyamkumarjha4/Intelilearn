export type HoldReason = "hover" | "focus" | "touch" | "hidden";

/** Time and timers, so the rules can be tested without waiting. */
export interface Clock {
  now(): number;
  set(run: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

const BROWSER_CLOCK: Clock = {
  now: () => Date.now(),
  set: (run, ms) => setTimeout(run, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/**
 * The timer and pause rules of an auto-advancing carousel. It calls `onAdvance` every `intervalMs` while it is enabled
 * and nothing holds it. A hold (hover, keyboard focus, touch, off screen) stops the clock and remembers how much of the
 * interval was left; letting go of the last hold carries on with that. A touch lets go on its own `touchResumeMs` after
 * the finger lifts. `restart` is for a visitor's own choice of slide: the next one gets a whole interval.
 */
export class Autoplay {
  static readonly INTERVAL_MS = 6000;
  static readonly TOUCH_RESUME_MS = 4000;

  private readonly holds = new Set<HoldReason>();
  private enabled = false;
  private timer: unknown = null;
  private touchTimer: unknown = null;
  private left: number;
  private armedAt = 0;

  constructor(
    private readonly onAdvance: () => void,
    private readonly onPausedChange: (paused: boolean) => void = () => undefined,
    private readonly clock: Clock = BROWSER_CLOCK,
    private readonly intervalMs = Autoplay.INTERVAL_MS,
    private readonly touchResumeMs = Autoplay.TOUCH_RESUME_MS,
  ) {
    this.left = intervalMs;
  }

  get paused(): boolean {
    return this.holds.size > 0;
  }

  get running(): boolean {
    return this.enabled && !this.paused;
  }

  /** Off (for a visitor who asked for less motion) stops it for good; on starts a fresh interval. */
  setEnabled(on: boolean): void {
    if (on === this.enabled) return;
    this.enabled = on;
    if (on) {
      this.left = this.intervalMs;
      this.arm();
    } else {
      this.stop();
    }
  }

  hold(reason: HoldReason): void {
    if (this.holds.has(reason)) return;
    const wasPaused = this.paused;
    this.holds.add(reason);
    if (!wasPaused) {
      this.stop();
      this.onPausedChange(true);
    }
  }

  release(reason: HoldReason): void {
    if (!this.holds.delete(reason) || this.paused) return;
    this.arm();
    this.onPausedChange(false);
  }

  touchStart(): void {
    this.clearTouchTimer();
    this.hold("touch");
  }

  touchEnd(): void {
    this.clearTouchTimer();
    this.touchTimer = this.clock.set(() => {
      this.touchTimer = null;
      this.release("touch");
    }, this.touchResumeMs);
  }

  /** The visitor chose a slide: the next one gets a whole interval (counted from when the pause ends, if paused). */
  restart(): void {
    this.stop();
    this.left = this.intervalMs;
    this.arm();
  }

  dispose(): void {
    this.enabled = false;
    this.stop();
    this.clearTouchTimer();
  }

  private arm(): void {
    if (!this.running || this.timer !== null) return;
    this.armedAt = this.clock.now();
    this.timer = this.clock.set(() => {
      this.timer = null;
      this.onAdvance();
      this.left = this.intervalMs;
      this.arm();
    }, this.left);
  }

  /** Stops the clock, keeping how much of the interval was left. */
  private stop(): void {
    if (this.timer === null) return;
    this.clock.clear(this.timer);
    this.timer = null;
    this.left = Math.max(0, this.left - (this.clock.now() - this.armedAt));
  }

  private clearTouchTimer(): void {
    if (this.touchTimer === null) return;
    this.clock.clear(this.touchTimer);
    this.touchTimer = null;
  }
}
