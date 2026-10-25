/** The arithmetic of a looping, swipeable row of slides. */
export class SlideCycle {
  static next(index: number, count: number): number {
    return count === 0 ? 0 : (index + 1) % count;
  }

  static previous(index: number, count: number): number {
    return count === 0 ? 0 : (index - 1 + count) % count;
  }

  /** The slide an arrow key leads to, or null for any other key. */
  static byKey(key: string, index: number, count: number): number | null {
    if (key === "ArrowRight") return SlideCycle.next(index, count);
    if (key === "ArrowLeft") return SlideCycle.previous(index, count);
    return null;
  }

  /** The slide a scroll position has settled on, for a track of equal slides `width` wide with `gap` between them. */
  static fromScroll(scrollLeft: number, width: number, gap: number, count: number): number {
    if (width <= 0 || count <= 0) return 0;
    return Math.min(Math.max(Math.round(scrollLeft / (width + gap)), 0), count - 1);
  }
}
