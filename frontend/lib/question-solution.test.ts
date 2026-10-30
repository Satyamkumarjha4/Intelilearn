/**
 * Unit under test: `QuestionSolution`, the small readings of a solution the practice sheet and the results share.
 *
 * Why: a multiple-select question has several right options and a multiple-choice one has one. If the sheet only reads
 * `correct_index` it shows nothing for the first kind; and "1 marks" reads as a mistake.
 *
 * Use cases:
 * - a multiple-select question gives its right options in order, a multiple-choice question gives its one
 * - a solution with neither (a written answer) gives none
 * - marks are worded as "1 mark" and "2 marks"
 */
import { describe, expect, test } from "bun:test";

import { QuestionSolution } from "@/lib/question-solution";

describe("QuestionSolution.correctOptions", () => {
  test("a multiple-select question gives all its right options, sorted", () => {
    expect(QuestionSolution.correctOptions({ correct_indices: [2, 0] })).toEqual([0, 2]);
  });

  test("a multiple-choice question gives its one", () => {
    expect(QuestionSolution.correctOptions({ correct_index: 0 })).toEqual([0]);
  });

  test("the list wins when a solution has both, and an empty list falls back to the single index", () => {
    expect(QuestionSolution.correctOptions({ correct_index: 1, correct_indices: [3, 2] })).toEqual([2, 3]);
    expect(QuestionSolution.correctOptions({ correct_index: 1, correct_indices: [] })).toEqual([1]);
  });

  test("a solution without options gives none", () => {
    expect(QuestionSolution.correctOptions({})).toBeUndefined();
  });
});

describe("QuestionSolution.marks", () => {
  test.each([
    [1, "1 mark"],
    [2, "2 marks"],
    [0, "0 marks"],
  ])("%i is %s", (count, text) => {
    expect(QuestionSolution.marks(count)).toBe(text);
  });
});
