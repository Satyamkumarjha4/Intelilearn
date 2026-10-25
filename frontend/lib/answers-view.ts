import type { QuizResultSummary, ReviewQuestion } from "@/lib/types";

export type Verdict = { kind: "right" | "wrong" | "unsure"; label: string };
export type OptionMark = { tone: "correct" | "wrong" | "plain"; picked: boolean };

/** How an answered quick check is told in the read-only answers tab. */
export class AnswersView {
  static verdict(question: ReviewQuestion): Verdict {
    if (question.answer === "dont_know") return { kind: "unsure", label: "You said “I don't know”" };
    return question.correct ? { kind: "right", label: "Correct" } : { kind: "wrong", label: "Not quite" };
  }

  /** The right option is always marked; the learner's own wrong pick is marked wrong; the others stay plain. */
  static option(question: ReviewQuestion, index: number): OptionMark {
    const picked = question.answer === index;
    if (index === question.correct_index) return { tone: "correct", picked };
    return { tone: picked ? "wrong" : "plain", picked };
  }

  /** The badge colour for a verdict. A miss is amber (something to learn), not red: this is not an exam. */
  static badge(kind: Verdict["kind"]): "success" | "marigold" | "secondary" {
    return { right: "success", wrong: "marigold", unsure: "secondary" }[kind] as "success" | "marigold" | "secondary";
  }

  static score(result: QuizResultSummary): string {
    return `${result.correct} / ${result.total}`;
  }
}
