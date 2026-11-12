/**
 * The wait before "Send a new code" works again. The server holds the real limit (a code a minute) and says how long in
 * `Retry-After` when it refuses; this only keeps the button honest so a person is not invited to press what will be refused.
 * Time comes from outside, so a test moves it instead of waiting.
 */
export class ResendClock {
  static readonly COOLDOWN_SECONDS = 60;
  private until = 0;

  constructor(private readonly now: () => number = () => Date.now()) {}

  /** Wait `seconds` from now (a minute when the server did not say). */
  start(seconds: number | null = null): void {
    const wait = seconds === null || !Number.isFinite(seconds) || seconds <= 0 ? ResendClock.COOLDOWN_SECONDS : seconds;
    this.until = this.now() + wait * 1000;
  }

  /** Whole seconds left, never below zero. */
  remaining(): number {
    return Math.max(0, Math.ceil((this.until - this.now()) / 1000));
  }

  ready(): boolean {
    return this.remaining() === 0;
  }

  /** The words on the button. */
  label(): string {
    const left = this.remaining();
    return left > 0 ? `Send a new code in ${left}s` : "Send a new code";
  }
}
