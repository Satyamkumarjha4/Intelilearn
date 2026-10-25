import { ApiError } from "@/lib/api";
import { FlowBands, type BandSettings } from "@/lib/flow-bands";
import type { FlowSettingsValues } from "@/lib/types";

type NumberField = {
  [K in keyof FlowSettingsValues]: FlowSettingsValues[K] extends number ? K : never;
}[keyof FlowSettingsValues];
type ListField = "media_sources" | "allowed_media_licenses";

/** What the boxes hold: text for the numbers (it is not a number while someone types), the rest as it is. */
export type FlowForm = { [K in NumberField]: string } & Pick<FlowSettingsValues, "mastery_requires_all_correct" | ListField>;
export type FlowErrors = Partial<Record<keyof FlowSettingsValues, string>>;

/** The limits the model puts on a field (`PositiveSmallIntegerField` is 0 to 32767; some have validators on top). */
const SMALL_INT_MAX = 32767;
const RANGES: Record<NumberField, [min: number, max: number]> = {
  diagnostic_questions_per_band: [1, 4],
  prerequisite_question_count: [1, 10],
  prereq_trigger_max_correct: [0, SMALL_INT_MAX],
  final_test_min: [1, SMALL_INT_MAX],
  final_test_max: [1, SMALL_INT_MAX],
  max_interactives_per_page: [0, SMALL_INT_MAX],
  alignment_min_score: [1, 5],
  alignment_max_rounds: [0, SMALL_INT_MAX],
  render_check_max_rounds: [0, SMALL_INT_MAX],
  max_auto_runtime_repairs: [0, SMALL_INT_MAX],
};
const NUMBERS = Object.keys(RANGES) as NumberField[];
const LISTS: ListField[] = ["media_sources", "allowed_media_licenses"];

/** The Lesson settings form: what the boxes hold, whether it is valid, and the patch that saving sends. */
export class FlowSettingsForm {
  static fromSettings(values: FlowSettingsValues): FlowForm {
    const form = { mastery_requires_all_correct: values.mastery_requires_all_correct } as FlowForm;
    for (const field of NUMBERS) form[field] = String(values[field]);
    for (const field of LISTS) form[field] = [...values[field]];
    return form;
  }

  static errors(form: FlowForm): FlowErrors {
    const errors: FlowErrors = {};
    for (const field of NUMBERS) {
      const message = FlowSettingsForm.rangeError(field, form[field]);
      if (message) errors[field] = message;
    }
    const value = (field: NumberField) => FlowSettingsForm.parse(form[field]);

    const [min, max] = [value("final_test_min"), value("final_test_max")];
    if (!errors.final_test_min && !errors.final_test_max && min !== null && max !== null && max < min) {
      errors.final_test_max = `Must be at least the minimum (${min}).`;
    }
    const perBand = value("diagnostic_questions_per_band");
    const cutoff = value("prereq_trigger_max_correct");
    if (!errors.diagnostic_questions_per_band && !errors.prereq_trigger_max_correct && perBand !== null && cutoff !== null) {
      const total = perBand * FlowBands.LEVELS;
      if (cutoff > total) errors.prereq_trigger_max_correct = `The quick check has only ${total} questions.`;
    }
    return errors;
  }

  /** The fields that differ from what is saved, in form order. A box that holds nonsense differs. */
  static dirty(saved: FlowSettingsValues, form: FlowForm): (keyof FlowSettingsValues)[] {
    const fields: (keyof FlowSettingsValues)[] = [];
    for (const field of NUMBERS) if (FlowSettingsForm.parse(form[field]) !== saved[field]) fields.push(field);
    if (form.mastery_requires_all_correct !== saved.mastery_requires_all_correct) fields.push("mastery_requires_all_correct");
    for (const field of LISTS) if (!FlowSettingsForm.sameSet(form[field], saved[field])) fields.push(field);
    return fields;
  }

  /** The body of the `PATCH`: the changed fields, as numbers. A box that holds nonsense is left out. */
  static patch(saved: FlowSettingsValues, form: FlowForm): Partial<FlowSettingsValues> {
    const patch: Record<string, unknown> = {};
    for (const field of FlowSettingsForm.dirty(saved, form)) {
      if ((NUMBERS as string[]).includes(field)) {
        const number = FlowSettingsForm.parse(form[field as NumberField]);
        if (number !== null) patch[field] = number;
      } else {
        patch[field] = form[field as keyof FlowForm];
      }
    }
    return patch as Partial<FlowSettingsValues>;
  }

  /** The form as numbers for the live preview: a box that holds nonsense counts as its saved value. */
  static numbers(saved: FlowSettingsValues, form: FlowForm): BandSettings & FlowSettingsValues {
    const values = { ...saved, mastery_requires_all_correct: form.mastery_requires_all_correct };
    for (const field of NUMBERS) values[field] = FlowSettingsForm.parse(form[field]) ?? saved[field];
    return values;
  }

  /** The list with `value` switched on or off: options in the page's order, then values the page does not list. */
  static toggle(current: readonly string[], value: string, options: readonly string[]): string[] {
    const wanted = new Set(current);
    if (wanted.has(value)) wanted.delete(value);
    else wanted.add(value);
    return [...options.filter((option) => wanted.has(option)), ...current.filter((item) => !options.includes(item) && wanted.has(item))];
  }

  /** The API's refusal as one message per field (empty when the failure is not about a field). */
  static serverErrors(error: unknown): FlowErrors {
    if (!(error instanceof ApiError)) return {};
    return Object.fromEntries(Object.entries(error.fields).filter(([, messages]) => messages.length).map(([field, messages]) => [field, messages[0]]));
  }

  private static rangeError(field: NumberField, text: string): string | null {
    const number = FlowSettingsForm.parse(text);
    if (number === null) return "Enter a whole number.";
    const [min, max] = RANGES[field];
    return number < min || number > max ? `Enter a number from ${min} to ${max}.` : null;
  }

  /** A whole number from text, or null. */
  private static parse(text: string): number | null {
    const trimmed = text.trim();
    return /^\d+$/.test(trimmed) ? Number(trimmed) : null;
  }

  private static sameSet(a: readonly string[], b: readonly string[]): boolean {
    return a.length === b.length && [...a].sort().join("\n") === [...b].sort().join("\n");
  }
}
