/**
 * What a person types or pastes into the box for the emailed code. People paste `123 456` or `123-456` from an email,
 * add a stray space, or type a letter by mistake: only the digits count, and only as many as the code has.
 */
export class CodeEntry {
  static readonly LENGTH = 6;

  /** The digits in `raw`, in order, cut to `length`. */
  static digits(raw: string, length = CodeEntry.LENGTH): string {
    return raw.replace(/\D/g, "").slice(0, length);
  }

  /** Whether `raw` holds a whole code (the screen sends it as soon as it does). */
  static isComplete(raw: string, length = CodeEntry.LENGTH): boolean {
    return CodeEntry.digits(raw, length).length === length;
  }

  /** The six boxes of the screen: one character each, blank where nothing is typed yet. */
  static boxes(raw: string, length = CodeEntry.LENGTH): string[] {
    const digits = CodeEntry.digits(raw, length);
    return Array.from({ length }, (_, index) => digits[index] ?? "");
  }
}
