/**
 * Unit under test: `LessonPdf`, which builds a downloadable PDF of a lesson's reading pages from the page content.
 *
 * Why: learners print the lesson to read offline. A builder that throws on one optional field, or prints raw Markdown
 * and LaTeX, leaves them with nothing; and the test page (answers are collected in the sandbox) must never be in it.
 *
 * Use cases:
 * - the three reading pages render to a real PDF with one PDF page at least per lesson page
 * - sections with every optional part (formula, example, code, callout) and with none both render
 * - the pages are taken in reading order, a missing page is skipped and the test page is never included
 */
import { describe, expect, test } from "bun:test";
import { renderToBuffer } from "@react-pdf/renderer";

import { LessonPdf } from "./lesson-pdf";
import type { LessonPageContent, LessonSection } from "@/lib/types";

const bare: LessonSection = { id: "s1", heading: "Halving", body: "Cut the **range** in half.", key_points: [], worked_examples: [], formulas: [], code_snippets: [], callouts: [] };
const full: LessonSection = {
  ...bare,
  id: "s2",
  heading: "Cost",
  key_points: ["Each step halves n"],
  formulas: [{ latex: "T(n) = O(\\log n)", explanation: "Logarithmic" }],
  worked_examples: [{ problem: "Find 7", solution: "Check the middle." }],
  code_snippets: [{ language: "python", code: "def f(x):\n    return x", explanation: "A function" }],
  callouts: [{ kind: "tip", text: "Mind $n=0$." }],
};
const page = (key: string, sections: LessonSection[]): LessonPageContent => ({ key, title: `Page ${key}`, sections, summary: "Recap" });

async function render(pages: LessonPageContent[]) {
  const buffer = await renderToBuffer(LessonPdf.element("Binary **search**", pages));
  return { buffer, text: buffer.toString("latin1") };
}

describe("LessonPdf", () => {
  test("renders the three reading pages to a real PDF", async () => {
    const { buffer, text } = await render([page("introduction", [bare]), page("core", [full]), page("advanced", [bare])]);

    expect(buffer.subarray(0, 4).toString()).toBe("%PDF");
    expect((text.match(/\/Type \/Page\b/g) ?? []).length).toBeGreaterThanOrEqual(3);
  });

  test("renders sections with all, and with none, of the optional parts", async () => {
    const { buffer } = await render([page("core", [bare, full])]);

    expect(buffer.length).toBeGreaterThan(500);
  });

  test("takes the pages in reading order, skips a missing one, and never includes the test page", () => {
    const pages = {
      advanced: page("advanced", []),
      test: page("test", []),
      introduction: page("introduction", []),
    };

    expect(LessonPdf.pagesOf({ pages }).map((p) => p.key)).toEqual(["introduction", "advanced"]);
    expect(LessonPdf.pagesOf({})).toEqual([]);
  });
});
