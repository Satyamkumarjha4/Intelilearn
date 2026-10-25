/**
 * Unit under test: `LegalDocument`, which reads a legal page's copy (a markdown file under content/legal) into its
 * "last updated" date, introduction, numbered sections and tables.
 *
 * Why: the copy is edited as plain markdown by someone who is not touching components, so the page must cope with
 * whatever they write: a missing date, a section with no number, two sections with the same title, a table in the
 * middle of a list of paragraphs. The table of contents and the anchors come from this, so a wrong id is a dead link.
 * The two real files are checked too, so an edit that breaks the page fails here and not in the browser.
 *
 * Use cases:
 * - the "Last updated" line becomes the date, and is not part of the text
 * - the text before the first section is the introduction
 * - each `###` heading is a section with its number, title and an anchor made from the title
 * - two sections with one title get different anchors
 * - a section without a number keeps its title
 * - a table becomes headers and rows (inline code kept as text), and the text around it stays text, in order
 * - a file with no sections, no date or nothing at all still reads
 * - the real privacy and terms copy: dated, with numbered sections 1..n in order, unique anchors, and no other email
 *   than the contact address
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { CONTACT } from "../content/legal/contact";
import { LegalDocument } from "./legal-document";

describe("parse", () => {
  const md = `**Last updated: 25 October 2026**

Intro one,
continued.

### 1. Summary
- a
- b

### 2. What we collect

Before.

| Name | Purpose |
|---|---|
| \`lc_access\` | Keeps you signed in |
| \`csrftoken\` | Protects forms |

After.
`;

  test("reads the date, the introduction and the sections", () => {
    const doc = LegalDocument.parse(md);

    expect(doc.updated).toBe("25 October 2026");
    expect(doc.intro).toEqual([{ kind: "text", markdown: "Intro one,\ncontinued." }]);
    expect(doc.sections.map((s) => [s.number, s.title, s.id])).toEqual([[1, "Summary", "summary"], [2, "What we collect", "what-we-collect"]]);
    expect(doc.sections[0].blocks).toEqual([{ kind: "text", markdown: "- a\n- b" }]);
  });

  test("a table becomes headers and rows, with the text around it kept in order", () => {
    const blocks = LegalDocument.parse(md).sections[1].blocks;

    expect(blocks).toEqual([
      { kind: "text", markdown: "Before." },
      { kind: "table", headers: ["Name", "Purpose"], rows: [["`lc_access`", "Keeps you signed in"], ["`csrftoken`", "Protects forms"]] },
      { kind: "text", markdown: "After." },
    ]);
  });

  test("two sections with one title get different anchors", () => {
    const ids = LegalDocument.parse("### 1. Contact\nx\n\n### 2. Contact\ny").sections.map((s) => s.id);

    expect(new Set(ids).size).toBe(2);
  });

  test("a section without a number keeps its title", () => {
    expect(LegalDocument.parse("### Hello there\nx").sections[0]).toMatchObject({ number: null, title: "Hello there", id: "hello-there" });
  });

  test.each([[""], ["just words"], ["**Last updated: soon**"], ["### \n"]])("%j still reads", (text) => {
    const doc = LegalDocument.parse(text);

    expect(Array.isArray(doc.sections) && Array.isArray(doc.intro)).toBe(true);
  });

  test("the date is empty when there is none", () => {
    expect(LegalDocument.parse("Intro").updated).toBe("");
  });
});

describe("the real copy", () => {
  const read = (name: string) => LegalDocument.parse(readFileSync(join(import.meta.dir, "../content/legal", `${name}.md`), "utf8"));

  test.each([["privacy", 10], ["terms", 13]])("%s has its date and %i numbered sections in order, with unique anchors", (name, count) => {
    const doc = read(name);

    expect(doc.updated).toBe("25 October 2026");
    expect(doc.sections.map((s) => s.number)).toEqual(Array.from({ length: count }, (_, n) => n + 1));
    expect(new Set(doc.sections.map((s) => s.id)).size).toBe(count);
  });

  test("the privacy policy has the cookie table", () => {
    const tables = read("privacy").sections.flatMap((s) => s.blocks).filter((b) => b.kind === "table");

    expect(tables).toHaveLength(1);
    expect(tables[0]).toMatchObject({ headers: ["Name", "Purpose", "How long"] });
  });

  test("the only email address in the copy is the contact address", () => {
    for (const name of ["privacy", "terms"]) {
      const text = readFileSync(join(import.meta.dir, "../content/legal", `${name}.md`), "utf8");
      const emails = new Set(text.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g));

      expect([...emails]).toEqual([CONTACT.email]);
    }
  });
});
