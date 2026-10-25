/** The "How it works" steps: which one is shown, and whether they are still playing on their own. */
export class Walkthrough {
  /** How long each step is shown while playing. */
  static readonly STEP_MS = 5000;

  private constructor(
    readonly index: number,
    readonly autoplay: boolean,
    readonly count: number,
  ) {}

  static start(count: number, autoplay = true): Walkthrough {
    return new Walkthrough(0, autoplay, count);
  }

  /** The next step, wrapping to the first. Keeps playing (or not). */
  advance(): Walkthrough {
    return new Walkthrough((this.index + 1) % this.count, this.autoplay, this.count);
  }

  /** The visitor picked a step: show it and leave them in charge from now on. */
  choose(index: number): Walkthrough {
    return new Walkthrough(Math.min(Math.max(index, 0), this.count - 1), false, this.count);
  }

  /** The arrow keys: a step either way, wrapping, and the visitor is in charge. */
  step(direction: 1 | -1): Walkthrough {
    return new Walkthrough((this.index + direction + this.count) % this.count, false, this.count);
  }
}
