import type { ConsoleTestimonial, TestimonialDraft, TestimonialInput } from "./types";

export type TestimonialProblems = Partial<Record<"name" | "context" | "quote" | "rating" | "is_published", string>>;

/**
 * The testimonial form: what is wrong with it before anything is sent, what is sent, and why a testimonial cannot be
 * published yet. The server checks all of it again (and the database holds the consent rule); this only spares a round trip
 * and says why a button is off.
 */
export class TestimonialForm {
  static readonly QUOTE_MAX = 300;
  static readonly NAME_MAX = 80;

  static blank(): TestimonialDraft {
    return { name: "", context: "", quote: "", rating: "", consent_confirmed: false, is_published: false };
  }

  static from(row: ConsoleTestimonial): TestimonialDraft {
    return {
      name: row.name,
      context: row.context,
      quote: row.quote,
      rating: row.rating === null ? "" : String(row.rating),
      consent_confirmed: row.consent_confirmed,
      is_published: row.is_published,
    };
  }

  /** The rating typed: empty is none, else a whole number from 1 to 5; null when it is neither. */
  static rating(text: string): number | null | undefined {
    const trimmed = text.trim();
    if (trimmed === "") return null;
    return /^[1-5]$/.test(trimmed) ? Number(trimmed) : undefined;
  }

  static problems(draft: TestimonialDraft, isSample = false): TestimonialProblems {
    const found: TestimonialProblems = {};
    if (!draft.name.trim()) found.name = "Give the name the learner agreed to be shown under.";
    else if (draft.name.trim().length > TestimonialForm.NAME_MAX) found.name = `At most ${TestimonialForm.NAME_MAX} characters.`;
    if (!draft.context.trim()) found.context = 'Say who they are, for example "Class 12 student".';
    else if (draft.context.trim().length > TestimonialForm.NAME_MAX) found.context = `At most ${TestimonialForm.NAME_MAX} characters.`;
    if (!draft.quote.trim()) found.quote = "Write what they said.";
    else if (draft.quote.trim().length > TestimonialForm.QUOTE_MAX) found.quote = `At most ${TestimonialForm.QUOTE_MAX} characters.`;
    if (TestimonialForm.rating(draft.rating) === undefined) found.rating = "A rating is 1 to 5, or leave it empty.";
    const why = TestimonialForm.cannotPublish(draft, isSample);
    if (draft.is_published && why) found.is_published = why;
    return found;
  }

  /** Why this cannot be published, or null when it can. */
  static cannotPublish(draft: Pick<TestimonialDraft, "consent_confirmed">, isSample: boolean): string | null {
    if (isSample) return "A sample is a placeholder for development and can never be published.";
    if (!draft.consent_confirmed) return "Confirm that the learner agreed to be quoted before publishing.";
    return null;
  }

  static payload(draft: TestimonialDraft): TestimonialInput {
    return {
      name: draft.name.trim(),
      context: draft.context.trim(),
      quote: draft.quote.trim(),
      rating: TestimonialForm.rating(draft.rating) ?? null,
      consent_confirmed: draft.consent_confirmed,
      is_published: draft.is_published,
    };
  }

  /** Only what differs from the saved row, so an edit sends no more than it changes. */
  static changes(row: ConsoleTestimonial, draft: TestimonialDraft): Partial<TestimonialInput> {
    const next = TestimonialForm.payload(draft);
    const saved = TestimonialForm.payload(TestimonialForm.from(row));
    const changed: Partial<TestimonialInput> = {};
    for (const key of Object.keys(next) as (keyof TestimonialInput)[]) {
      if (next[key] !== saved[key]) (changed as Record<string, unknown>)[key] = next[key];
    }
    return changed;
  }

  /** The ids in the order they would be in after moving one place up (-1) or down (1); the same order at either end. */
  static move(ids: number[], id: number, direction: -1 | 1): number[] {
    const from = ids.indexOf(id);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= ids.length) return ids;
    const next = [...ids];
    [next[from], next[to]] = [next[to], next[from]];
    return next;
  }

  /** "37 / 300", for under the quote box. */
  static count(quote: string): string {
    return `${quote.trim().length} / ${TestimonialForm.QUOTE_MAX}`;
  }
}
