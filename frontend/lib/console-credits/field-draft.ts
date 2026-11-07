export type DraftValue = string | boolean;
export type Draft = Record<string, DraftValue>;
type Saved = Record<string, number | boolean | string>;

/**
 * An edit in progress over a saved record of numbers, switches and words (a plan, the credit settings). Numbers are
 * held as the text typed, because what is typed on the way to a number is not one yet. It says what changed, what is
 * not valid, and the patch to send, which holds only what changed and has numbers as numbers.
 */
export class FieldDraft {
  static from(saved: Saved): Draft {
    return Object.fromEntries(Object.entries(saved).map(([field, value]) => [field, typeof value === "number" ? String(value) : value]));
  }

  /** The fields whose draft differs from what is saved, in the saved order. */
  static dirty(saved: Saved, draft: Draft): string[] {
    return Object.keys(saved).filter((field) => field in draft && FieldDraft.differs(saved[field], draft[field]));
  }

  /** A message for each number that is not a whole number of at least 0. Words and switches are not judged here. */
  static errors(saved: Saved, draft: Draft): Record<string, string> {
    const found: Record<string, string> = {};
    for (const field of Object.keys(saved)) {
      if (typeof saved[field] === "number" && field in draft && FieldDraft.whole(draft[field]) === null) found[field] = "Enter a whole number.";
    }
    return found;
  }

  /** What to send: only what changed (a box that is not a number yet is left out), numbers as numbers. */
  static patch(saved: Saved, draft: Draft): Record<string, number | boolean | string> {
    const patch: Record<string, number | boolean | string> = {};
    for (const field of FieldDraft.dirty(saved, draft)) {
      const value = draft[field];
      if (typeof saved[field] === "number") {
        const number = FieldDraft.whole(value);
        if (number !== null) patch[field] = number;
      } else {
        patch[field] = value;
      }
    }
    return patch;
  }

  /** The number a box holds, or null when it is empty, has spaces inside, a sign, a point, or anything but digits. */
  static whole(value: DraftValue): number | null {
    if (typeof value !== "string") return null;
    const text = value.trim();
    return /^\d{1,9}$/.test(text) ? Number(text) : null;
  }

  private static differs(saved: number | boolean | string, draft: DraftValue): boolean {
    return typeof saved === "number" ? String(saved) !== (typeof draft === "string" ? draft.trim() : draft) : saved !== draft;
  }
}
