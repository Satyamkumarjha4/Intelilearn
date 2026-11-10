/** The example scores in the landing page's "Your tries" chart. They are drawn as an example, captioned as one, and the
 *  "up N points" line is worked out from them so the words and the bars cannot disagree. */
export class ProgressExample {
  static readonly TRIES = [45, 62, 85];

  /** Points gained on the last try over the one before. */
  static get gain(): number {
    const tries = ProgressExample.TRIES;
    return tries[tries.length - 1] - tries[tries.length - 2];
  }

  static get label(): string {
    return `Example scores: ${ProgressExample.TRIES.map((score, index) => `attempt ${index + 1}, ${score} percent`).join("; ")}`;
  }

  /** The word under each bar: the best try is named. */
  static caption(index: number): string {
    return `Try ${index + 1}${ProgressExample.TRIES[index] === Math.max(...ProgressExample.TRIES) ? " · best" : ""}`;
  }
}
