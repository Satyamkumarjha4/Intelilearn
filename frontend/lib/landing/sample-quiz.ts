import { SAMPLE_LEVELS, SAMPLE_QUESTIONS, type SampleLevel, type SampleQuestion } from "@/lib/landing/sample-quiz-content";

type State = { index: number; picked: number | null; score: number; done: boolean };

/**
 * The landing page's sample Quick check: three fixed questions, instant feedback, and a result that names the level the
 * score would give. Pure and immutable (every move returns the next quiz), so the card is a thin view over it and the
 * whole thing runs with no network and no model.
 */
export class SampleQuiz {
  private constructor(
    private readonly state: State,
    private readonly questions: readonly SampleQuestion[],
    private readonly levels: readonly SampleLevel[],
  ) {}

  static start(questions: readonly SampleQuestion[] = SAMPLE_QUESTIONS, levels: readonly SampleLevel[] = SAMPLE_LEVELS): SampleQuiz {
    return new SampleQuiz({ index: 0, picked: null, score: 0, done: false }, questions, levels);
  }

  // --- what the card shows ----------------------------------------------------------------------------------------

  get total(): number {
    return this.questions.length;
  }
  /** 1-based, for "2 of 3". */
  get number(): number {
    return this.state.index + 1;
  }
  get current(): SampleQuestion {
    return this.questions[this.state.index];
  }
  get picked(): number | null {
    return this.state.picked;
  }
  get answered(): boolean {
    return this.state.picked !== null;
  }
  get done(): boolean {
    return this.state.done;
  }
  get score(): number {
    return this.state.score;
  }
  get isLast(): boolean {
    return this.state.index === this.questions.length - 1;
  }
  get nextLabel(): string {
    return this.isLast ? "See my lesson" : "Next question";
  }
  /** 0 to 1: a question counts once it is answered. */
  get progress(): number {
    return (this.state.index + (this.answered ? 1 : 0)) / this.questions.length;
  }
  /** "Right. …" or "Not quite. …", with the reason; empty until an answer is picked. */
  get feedback(): string {
    if (!this.answered) return "";
    return `${this.state.picked === this.current.answer ? "Right." : "Not quite."} ${this.current.why}`;
  }
  /** What an option looks like: the right one once answered, the one picked if it was wrong, and the rest. */
  optionState(option: number): "open" | "right" | "wrong" | "rest" {
    if (!this.answered) return "open";
    if (option === this.current.answer) return "right";
    return option === this.state.picked ? "wrong" : "rest";
  }

  // --- the result -------------------------------------------------------------------------------------------------

  get level(): SampleLevel {
    return this.levels[Math.min(this.state.score, this.levels.length - 1)];
  }

  // --- moves ------------------------------------------------------------------------------------------------------

  /** Choose an option. The first choice counts: later ones, and ones that are not options, change nothing. */
  pick(option: number): SampleQuiz {
    if (this.state.done || this.answered || !Number.isInteger(option) || option < 0 || option >= this.current.options.length) return this;
    const right = option === this.current.answer ? 1 : 0;
    return this.with({ picked: option, score: this.state.score + right });
  }

  /** On to the next question, or to the result after the last. Nothing happens before an answer is picked. */
  next(): SampleQuiz {
    if (this.state.done || !this.answered) return this;
    return this.isLast ? this.with({ done: true }) : this.with({ index: this.state.index + 1, picked: null });
  }

  restart(): SampleQuiz {
    return SampleQuiz.start(this.questions, this.levels);
  }

  private with(change: Partial<State>): SampleQuiz {
    return new SampleQuiz({ ...this.state, ...change }, this.questions, this.levels);
  }
}
