/** Which landing-page parts wait to pop in on scroll, and how the ones in a group are staggered. */
export class RevealPolicy {
  /** Nothing within this share of the screen's height (from the top) is held back: the visitor can already see it. */
  static readonly FOLD = 0.92;
  static readonly STAGGER_S = 0.08;

  static startsHidden(top: number, viewportHeight: number): boolean {
    return top > viewportHeight * RevealPolicy.FOLD;
  }

  /** The CSS delay of the n-th item in a group (counting from 0). */
  static delay(index: number): string {
    return `${Math.round(index * RevealPolicy.STAGGER_S * 1000) / 1000}s`;
  }
}
