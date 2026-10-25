/** How a card leaves and arrives in a deck: the answered card flies off to the left, the next rises from the stack. */
export class DeckMotion {
  static readonly FLY_MS = 450;
  static readonly FLY: Keyframe[] = [
    { transform: "translateX(0) rotate(0)", opacity: 1 },
    { transform: "translateX(-120%) rotate(-8deg)", opacity: 0 },
  ];
  static readonly RISE: Keyframe[] = [
    { transform: "translateY(14px) scale(0.96)", opacity: 0.6 },
    { transform: "none", opacity: 1 },
  ];

  static prefersLessMotion(): boolean {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  static fly(card: HTMLElement | null): void {
    card?.animate?.(DeckMotion.FLY, { duration: DeckMotion.FLY_MS, easing: "ease-in", fill: "forwards" });
  }

  static rise(card: HTMLElement | null): void {
    card?.animate?.(DeckMotion.RISE, { duration: DeckMotion.FLY_MS, easing: "ease-out" });
  }
}
