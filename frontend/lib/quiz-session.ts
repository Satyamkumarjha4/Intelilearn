import type { Answer, LearnerQuestion } from "@/lib/types";

export const DONT_KNOW = "dont_know" as const;

/**
 * A learner working through a quiz: one question at a time, every question answered before submitting.
 * "I don't know" is an answer (the useful one when unsure) and scores as wrong on the server.
 */
export class QuizSession {
  private readonly answers = new Map<string, Answer>();
  index = 0;

  constructor(readonly questions: LearnerQuestion[]) {}

  get current(): LearnerQuestion | undefined {
    return this.questions[this.index];
  }

  get answered(): number {
    return this.answers.size;
  }

  get progress(): number {
    return this.questions.length === 0 ? 0 : this.answered / this.questions.length;
  }

  get isComplete(): boolean {
    return this.questions.length > 0 && this.answered === this.questions.length;
  }

  get isLast(): boolean {
    return this.index === this.questions.length - 1;
  }

  answerOf(questionId: string): Answer | undefined {
    return this.answers.get(questionId);
  }

  /** Record an answer for the current question. */
  answer(value: Answer): void {
    const question = this.current;
    if (!question) return;
    if (value !== DONT_KNOW && (!Number.isInteger(value) || value < 0 || value >= question.options.length)) {
      throw new RangeError(`Option ${value} does not exist`);
    }
    this.answers.set(question.id, value);
  }

  next(): void {
    if (this.index < this.questions.length - 1) this.index += 1;
  }

  back(): void {
    if (this.index > 0) this.index -= 1;
  }

  /** The first question without an answer, or undefined when all are answered. */
  firstUnanswered(): number | undefined {
    const at = this.questions.findIndex((q) => !this.answers.has(q.id));
    return at === -1 ? undefined : at;
  }

  payload(): Record<string, Answer> {
    if (!this.isComplete) throw new Error("Answer every question before submitting");
    return Object.fromEntries(this.answers);
  }
}
