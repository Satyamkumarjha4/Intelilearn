/**
 * Unit under test: `PlainText`, which turns a sheet's Markdown and LaTeX into the plain text of a PDF.
 *
 * Why: the PDF has no Markdown or maths renderer. Printing `**bold**` or `\frac{1}{2}` raw makes a study sheet look
 * broken, which is what the learner takes to the exam.
 *
 * Use cases:
 * - strips emphasis, headings, inline code and links down to their text
 * - turns list markers into bullets
 * - unwraps inline and display maths and replaces common LaTeX commands with symbols
 * - unwraps fenced code and leaves plain text alone
 */
import { describe, expect, test } from "bun:test";

import { PlainText } from "./plain-text";

describe("PlainText.of", () => {
  test("strips emphasis, headings, inline code and links down to their text", () => {
    expect(PlainText.of("# Title\n**bold** and *italic* and `code` and [a link](https://x.y)")).toBe(
      "Title\nbold and italic and code and a link",
    );
  });

  test("turns list markers into bullets", () => {
    expect(PlainText.of("- one\n* two")).toBe("• one\n• two");
  });

  test("unwraps inline and display maths and replaces common commands", () => {
    expect(PlainText.of("Cost is $O(\\log n)$ and $$a \\leq b \\times c$$")).toBe("Cost is O(log n) and a ≤ b × c");
    expect(PlainText.of("$x^{2}$")).toBe("x^2");
  });

  test("unwraps fenced code and leaves plain text alone", () => {
    expect(PlainText.of("```python\nx = 1\n```")).toBe("x = 1");
    expect(PlainText.of("Just words, 3 * 4 = 12.")).toBe("Just words, 3 * 4 = 12.");
  });
});
