import type { Solution } from "@/lib/types";

/** What the server shows of a question's answer once the learner has answered it. */
export class QuestionSolution {
  /** The right options of a multiple-choice or multiple-select question, in order; undefined for other kinds. */
  static correctOptions(solution: Pick<Solution, "correct_index" | "correct_indices">): number[] | undefined {
    if (solution.correct_indices?.length) return [...solution.correct_indices].sort((a, b) => a - b);
    return solution.correct_index === undefined ? undefined : [solution.correct_index];
  }

  /** "1 mark", "2 marks". */
  static marks(count: number): string {
    return `${count} ${count === 1 ? "mark" : "marks"}`;
  }
}
