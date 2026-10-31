import type { QuizQuestionType } from "@/lib/types";

export type TypeOption = { id: QuizQuestionType; label: string; hint: string };
/** What the topic judge said, as far as the kinds of question go; null (not judged yet, or it failed) offers them all. */
export type TopicKinds = { numerical: boolean; code: boolean } | null;

/**
 * The kinds of question a quiz can ask, and which of them the wizard shows. This is the same rule the server applies
 * when the quiz is made (`QuestionTypes.for_topic`): choice questions always, numerical ones only for a topic that is
 * about calculation, short and long answers only from ten questions. Showing less than the server allows is fine;
 * showing more would offer a choice that is refused.
 */
export class QuestionTypeCatalog {
  /** Short and long answers need room to be marked fairly, so a quiz must have at least this many questions. */
  static readonly WRITTEN_FROM = 10;

  static readonly ALL: readonly TypeOption[] = [
    { id: "mcq", label: "Multiple choice", hint: "Pick the one right answer." },
    { id: "msq", label: "Multiple select", hint: "Pick every answer that applies." },
    { id: "numerical", label: "Numbers", hint: "Work something out and type the number." },
    { id: "short_answer", label: "Short answers", hint: "A sentence or two." },
    { id: "long_answer", label: "Written answers", hint: "A longer answer, marked on points." },
  ];

  static label(id: QuizQuestionType): string {
    return QuestionTypeCatalog.ALL.find((option) => option.id === id)?.label ?? id;
  }

  static isWritten(id: QuizQuestionType): boolean {
    return id === "short_answer" || id === "long_answer";
  }

  /** The kinds to show for a topic and a number of questions, in the standard order. */
  static offered(kinds: TopicKinds, count: number): TypeOption[] {
    return QuestionTypeCatalog.ALL.filter(
      (option) =>
        (option.id !== "numerical" || kinds === null || kinds.numerical) &&
        (!QuestionTypeCatalog.isWritten(option.id) || count >= QuestionTypeCatalog.WRITTEN_FROM),
    );
  }

  /** What was picked, minus whatever the topic or the count no longer offers; multiple choice if nothing is left. */
  static keep(picked: readonly QuizQuestionType[], kinds: TopicKinds, count: number): QuizQuestionType[] {
    const offered = new Set(QuestionTypeCatalog.offered(kinds, count).map((option) => option.id));
    const kept = QuestionTypeCatalog.ALL.map((option) => option.id).filter((id) => picked.includes(id) && offered.has(id));
    return kept.length ? kept : ["mcq"];
  }

  /** Picks or drops one kind. The last one cannot be dropped: a quiz asks something. */
  static toggle(picked: readonly QuizQuestionType[], id: QuizQuestionType): QuizQuestionType[] {
    if (!picked.includes(id)) return QuestionTypeCatalog.ALL.map((o) => o.id).filter((kind) => kind === id || picked.includes(kind));
    return picked.length === 1 ? [...picked] : picked.filter((kind) => kind !== id);
  }

  /** A line under the kinds that explains why some are missing, or null when nothing is hidden for a reason worth saying. */
  static note(kinds: TopicKinds, count: number): string | null {
    if (count < QuestionTypeCatalog.WRITTEN_FROM) return `Short and written answers need ${QuestionTypeCatalog.WRITTEN_FROM} or more questions.`;
    if (kinds !== null && !kinds.numerical) return "This topic isn't about calculating, so there are no number questions.";
    return null;
  }
}
