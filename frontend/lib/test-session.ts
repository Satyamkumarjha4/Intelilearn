import type { QuestionResult, ScoreCard } from "@/lib/types";

/** How one question went, for colouring and wording. */
export type Tone = "full" | "partial" | "none" | "pending";

export class TestResultView {
  /** "14 of 20 marks (70%)", or what is known so far while the open-ended answers are being graded. */
  static summary(card: ScoreCard): string {
    const { awarded, available, percent } = card.score;
    const text = `${awarded} of ${available} marks (${percent}%)`;
    return card.complete ? text : `${text} so far`;
  }

  static tone(row: QuestionResult): Tone {
    if (row.awarded === null) return "pending";
    if (row.awarded >= row.marks) return "full";
    return row.awarded > 0 ? "partial" : "none";
  }

  static label(row: QuestionResult): string {
    switch (TestResultView.tone(row)) {
      case "pending":
        return "Being graded";
      case "full":
        return "Full marks";
      default:
        return `${row.awarded} of ${row.marks} marks`;
    }
  }

  /** Who marked it, in words: a person reading "graded by model" should not mistake it for a person. */
  static source(row: QuestionResult): string {
    return row.graded_by === "model" ? "Graded by AI" : row.graded_by === "auto" ? "Marked automatically" : "";
  }

  static topics(card: ScoreCard): string {
    return card.topics_to_revisit.join(", ");
  }
}
