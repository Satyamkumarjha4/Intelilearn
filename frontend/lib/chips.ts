/** How the topic chips of "Your starting point" are shown. The data is never changed, only its display. */
export class Chips {
  static readonly LIMIT = 6;

  /** Sentence case, keeping words that must keep their capitals: acronyms (DFS), words with digits or brackets
   *  (O(n)), a lone O or I, and words with a capital inside (JavaScript, pH). Text that is all capitals is shouting,
   *  so it is brought down entirely. */
  static sentence(text: string): string {
    const shouting = !/\p{Ll}/u.test(text);
    const words = text.trim().split(/\s+/).filter(Boolean);
    return words
      .map((word, index) => {
        const shown = word
          .split("-")
          .map((part) => (shouting || !Chips.keeps(part) ? part.toLowerCase() : part))
          .join("-");
        return index === 0 ? shown.charAt(0).toUpperCase() + shown.slice(1) : shown;
      })
      .join(" ");
  }

  /** The chips to show now and how many are tucked behind "+N more". One hidden chip is not worth a button. */
  static collapse(items: string[], limit: number, expanded: boolean): { shown: string[]; hidden: number } {
    if (expanded || items.length <= limit + 1) return { shown: items, hidden: 0 };
    return { shown: items.slice(0, limit), hidden: items.length - limit };
  }

  /** Whether there is a "+N more" button at all, so it can stay on screen as "Show fewer" once opened. */
  static collapsible(items: string[], limit: number): boolean {
    return items.length > limit + 1;
  }

  private static keeps(part: string): boolean {
    const letters = part.replace(/[^\p{L}]/gu, "");
    if (/\d/.test(part) || (/[()[\]]/.test(part) && /\p{Lu}/u.test(part))) return true;
    if (letters.length === 1) return letters === "O" || letters === "I";
    if (letters.length >= 2 && letters === letters.toUpperCase()) return true; // an acronym
    return /\p{Ll}\p{Lu}/u.test(letters); // a capital inside the word
  }
}
