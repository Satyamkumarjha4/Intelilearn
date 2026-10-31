export type AttemptKind = "test" | "quiz";

/** The words of the screen that takes an attempt, for a lesson's test and for a quick quiz (the copy of D9 and §11.7). */
export class AttemptWords {
  private constructor(
    readonly noun: string,
    readonly title: string,
    readonly subtitle: string,
    readonly cardsLabel: string,
  ) {}

  private static readonly KINDS: Record<AttemptKind, AttemptWords> = {
    test: new AttemptWords("test", "Test", "Show what you learned", "Test questions"),
    quiz: new AttemptWords("quiz", "Quick quiz", "See where you are", "Quiz questions"),
  };

  static of(kind: AttemptKind): AttemptWords {
    return AttemptWords.KINDS[kind];
  }

  get marking(): string {
    return `Marking your ${this.noun}`;
  }

  get confirmTitle(): string {
    return `Hand in your ${this.noun}?`;
  }

  get confirmText(): string {
    return "You'll see your score straight away. You can't change your answers after this, but you can try again later with new questions.";
  }

  get failedTitle(): string {
    return `We couldn't hand in your ${this.noun}`;
  }

  get handIn(): string {
    return `Hand in my ${this.noun}`;
  }

  get couldNotHandIn(): string {
    return `Could not hand in your ${this.noun}.`;
  }
}
