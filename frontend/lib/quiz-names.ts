import type { QuizKind } from "@/lib/types";

/** What a learner calls each check: the API's "diagnostic" and "prerequisite" are not their words. */
export class QuizNames {
  private static readonly NAMES: Record<QuizKind, string> = { diagnostic: "Quick check", prerequisite: "Foundations check" };

  static of(kind: QuizKind): string {
    return QuizNames.NAMES[kind];
  }

  static done(kind: QuizKind): string {
    return `${QuizNames.of(kind)} done!`;
  }

  static resultLabel(kind: QuizKind): string {
    return `${QuizNames.of(kind)} result`;
  }
}
