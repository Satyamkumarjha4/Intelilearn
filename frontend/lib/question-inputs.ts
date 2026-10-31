import type { QuestionType } from "@/lib/types";

/** What a learner types or picks for a question: an option, the options picked, or their own words. */
export type AnswerValue = number | number[] | string;
/** Which widget answers a kind of question; the component for each is chosen in `components/lessons/question-input.tsx`. */
export type Widget = "choice" | "multi" | "number" | "text" | "paragraph" | "code";

/** The parts of a question an input needs. Both the test screen and the practice sheet pass theirs. */
export type InputQuestion = {
  type: QuestionType;
  options?: string[];
  unit?: string;
  decimal_precision?: number;
  language?: string;
  starter_code?: string;
};

/** How one kind of question is answered. A new kind is a new class here and an entry in `QuestionInputs`. */
export abstract class QuestionInput {
  abstract readonly type: QuestionType;
  abstract readonly widget: Widget;
  abstract readonly label: string;
  /** What the test screen calls the field for a screen reader. */
  readonly answerLabel: string = "Your answer";

  /** One line that says how to answer, shown under the question; null when the kind needs none. */
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- the parameter documents what an override receives
  instruction(question: InputQuestion): string | null {
    return null;
  }

  isAnswered(answer: AnswerValue | undefined): boolean {
    if (answer === undefined) return false;
    if (Array.isArray(answer)) return answer.length > 0;
    return typeof answer !== "string" || answer.trim() !== "";
  }

  /** The new answer after `key` was pressed while the question is on screen, or undefined when the key is not for it. */
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- the parameters document what an override receives
  onKey(question: InputQuestion, current: AnswerValue | undefined, key: string): AnswerValue | null | undefined {
    return undefined;
  }

  /** The option a key stands for: 1 to 9, or a letter from "a"; null for anything else or an option that is not there. */
  protected optionOf(key: string, count: number): number | null {
    const index = /^[1-9]$/.test(key) ? Number(key) - 1 : key.length === 1 ? key.charCodeAt(0) - 97 : -1;
    return index >= 0 && index < count ? index : null;
  }
}

class McqInput extends QuestionInput {
  readonly type = "mcq";
  readonly widget = "choice";
  readonly label = "Multiple choice";
  readonly answerLabel = "Answers";

  onKey(question: InputQuestion, _current: AnswerValue | undefined, key: string) {
    return this.optionOf(key, question.options?.length ?? 0) ?? undefined;
  }
}

class MsqInput extends QuestionInput {
  readonly type = "msq";
  readonly widget = "multi";
  readonly label = "Multiple select";
  readonly answerLabel = "Answers";

  instruction(): string {
    return "Choose all that apply";
  }

  /** The options picked after the learner toggles one: sorted, and null when none is left (the card is unanswered). */
  toggle(current: AnswerValue | undefined, index: number): number[] | null {
    const picked = Array.isArray(current) ? current : [];
    const next = picked.includes(index) ? picked.filter((i) => i !== index) : [...picked, index];
    return next.length ? [...next].sort((a, b) => a - b) : null;
  }

  isPicked(answer: AnswerValue | undefined, index: number): boolean {
    return Array.isArray(answer) && answer.includes(index);
  }

  onKey(question: InputQuestion, current: AnswerValue | undefined, key: string) {
    const option = this.optionOf(key, question.options?.length ?? 0);
    return option === null ? undefined : this.toggle(current, option);
  }
}

class NumberInput extends QuestionInput {
  readonly type = "numerical";
  readonly widget = "number";
  readonly label = "Number";

  /** A hint about how many decimals the answer has. It never rejects an answer: only the tolerance decides that. */
  instruction(question: InputQuestion): string | null {
    const places = question.decimal_precision;
    if (places === undefined || places === null) return null;
    if (places === 0) return "Give a whole number";
    return `Give your answer to ${places} decimal ${places === 1 ? "place" : "places"}`;
  }

  /** `numeric` brings up the digits keypad on a phone; `decimal` adds the point. */
  inputMode(question: InputQuestion): "numeric" | "decimal" {
    return question.decimal_precision === 0 ? "numeric" : "decimal";
  }
}

class ShortTextInput extends QuestionInput {
  readonly type = "short_answer";
  readonly widget = "text";
  readonly label = "Short answer";
}

class LongTextInput extends QuestionInput {
  readonly type = "long_answer";
  readonly widget = "paragraph";
  readonly label = "Written answer";
}

/** Code questions of lessons from before code became a format of short and long answers. */
class CodeInput extends QuestionInput {
  readonly type = "code";
  readonly widget = "code";
  readonly label: string = "Code";

  /** What is in the box: the learner's code, or the starter code until they change it. */
  text(question: InputQuestion, answer: AnswerValue | undefined): string {
    return typeof answer === "string" ? answer : (question.starter_code ?? "");
  }

  /** Untouched starter code is not an answer. */
  isStarter(question: InputQuestion, value: string): boolean {
    return value.trim() === (question.starter_code ?? "").trim();
  }
}

/** A short or long answer about code: the same question, answered in the code editor instead of a text box. */
class CodeAnswerInput extends CodeInput {
  readonly label = "Code answer";
  readonly answerLabel = "Your code";

  instruction(): string {
    return "Write your code in the editor";
  }
}

/** The input of each kind of question, found by its `type`. */
export class QuestionInputs {
  static readonly mcq = new McqInput();
  static readonly msq = new MsqInput();
  static readonly number = new NumberInput();
  static readonly short = new ShortTextInput();
  static readonly long = new LongTextInput();
  static readonly code = new CodeInput();
  static readonly codeAnswer = new CodeAnswerInput();

  private static readonly BY_TYPE: Record<QuestionType, QuestionInput> = {
    mcq: QuestionInputs.mcq,
    msq: QuestionInputs.msq,
    numerical: QuestionInputs.number,
    short_answer: QuestionInputs.short,
    long_answer: QuestionInputs.long,
    code: QuestionInputs.code,
  };

  /** A kind the server may add before this page knows it is answered in a text box: still something to answer with. */
  static of(type: string): QuestionInput {
    return QuestionInputs.BY_TYPE[type as QuestionType] ?? QuestionInputs.long;
  }

  /**
   * The input for a question as it was written: a short or long answer that names a language is about code and is
   * answered in the code editor; anything else is its kind's input.
   */
  static forQuestion(question: Pick<InputQuestion, "type" | "language">): QuestionInput {
    const written = question.type === "short_answer" || question.type === "long_answer";
    return written && question.language?.trim() ? QuestionInputs.codeAnswer : QuestionInputs.of(question.type);
  }
}
