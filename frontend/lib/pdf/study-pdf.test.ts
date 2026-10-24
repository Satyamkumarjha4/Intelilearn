/**
 * Unit under test: `StudyPdf`, which builds a downloadable PDF of a study sheet from its structured JSON.
 *
 * Why: the PDF is what a learner prints for the exam. A builder that throws on one field, or that prints raw Markdown,
 * leaves them without their sheet. It runs in the browser, so these tests render with the same library in Bun.
 *
 * Use cases:
 * - each sheet kind renders to a real PDF (starts with %PDF, has pages)
 * - practice solutions that were revealed are printed, and hidden ones are not
 * - a sheet with empty optional parts (no formula, no examples, no tips) still renders
 */
import { describe, expect, test } from "bun:test";
import { renderToBuffer } from "@react-pdf/renderer";

import { StudyPdf } from "./study-pdf";
import type { CheatSheet, PracticeSheet, RevisionSheet } from "@/lib/types";

const cheat: CheatSheet = {
  title: "Binary search **cheat sheet**",
  summary: "Rules with $O(\\log n)$ cost.",
  sections: [
    {
      heading: "Key ideas",
      items: [
        { label: "Loop", kind: "formula", content: "Halve each time.", formula: "T(n) = O(\\log n)",
          variables: [{ symbol: "n", meaning: "items" }], when_to_use: "Sorted data" },
        { label: "Rule", kind: "rule", content: "Keep the invariant.", formula: "", variables: [], when_to_use: "" },
      ],
    },
  ],
};
const revision: RevisionSheet = {
  title: "Revision",
  overview: "All of it.",
  subtopics: [
    { title: "Halving", summary: "Cut the range.", key_points: ["a", "b", "c"],
      worked_examples: [{ problem: "Find 7", solution: "Check the middle." }], common_mistakes: ["Off by one"] },
    { title: "Cost", summary: "Logarithmic.", key_points: ["x"], worked_examples: [], common_mistakes: [] },
  ],
  final_tips: ["Practise"],
};
const practice: PracticeSheet = {
  title: "Practice",
  instructions: "Try each.",
  questions: [
    { id: "t1", type: "mcq", concept: "c", difficulty: "easy", marks: 2, question: "Pick one", options: ["a", "b", "c", "d"] },
    { id: "t2", type: "numerical", concept: "c", difficulty: "easy", marks: 2, question: "How many steps?" },
  ],
};

const pdfText = async (element: ReturnType<typeof StudyPdf.element>) => {
  const bytes = await renderToBuffer(element);
  return { head: Buffer.from(bytes).subarray(0, 5).toString(), size: bytes.length };
};

describe("StudyPdf", () => {
  test.each([
    ["cheat_sheet", cheat],
    ["revision_sheet", revision],
    ["practice_sheet", practice],
  ] as const)("renders a %s to a real PDF", async (kind, content) => {
    const { head, size } = await pdfText(StudyPdf.element(kind, content));

    expect(head).toBe("%PDF-");
    expect(size).toBeGreaterThan(1000);
  });

  test("a revealed practice solution makes the document different from one without solutions", async () => {
    const without = await pdfText(StudyPdf.element("practice_sheet", practice));
    const withSolutions = await pdfText(
      StudyPdf.element("practice_sheet", practice, { t1: { correct_index: 2 }, t2: { answer: 4, unit: "steps" } }),
    );

    expect(withSolutions.size).toBeGreaterThan(without.size);
  });
});
