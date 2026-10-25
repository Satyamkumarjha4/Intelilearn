export type Block = { kind: "text"; markdown: string } | { kind: "table"; headers: string[]; rows: string[][] };
export type Section = { id: string; number: number | null; title: string; blocks: Block[] };
export type ParsedLegal = { updated: string; intro: Block[]; sections: Section[] };

/** Reads the markdown of a legal page (content/legal) into what the page lays out. The copy is edited as plain
 *  markdown, so this takes whatever it finds and never throws. */
export class LegalDocument {
  static parse(source: string): ParsedLegal {
    let updated = "";
    const body = source.replace(/^\s*\*\*Last updated:\s*(.*?)\*\*\s*$/m, (_, date: string) => {
      updated = date.trim();
      return "";
    });
    const intro: string[] = [];
    const raw: { heading: string; lines: string[] }[] = [];
    for (const line of body.split("\n")) {
      const heading = /^###\s+(.*)$/.exec(line);
      if (heading) raw.push({ heading: heading[1].trim(), lines: [] });
      else (raw.at(-1)?.lines ?? intro).push(line);
    }
    const used = new Set<string>();
    const sections = raw
      .filter((r) => r.heading !== "")
      .map((r): Section => {
        const numbered = /^(\d+)\.\s+(.*)$/.exec(r.heading);
        const title = numbered ? numbered[2] : r.heading;
        return { id: LegalDocument.unique(LegalDocument.slug(title), used), number: numbered ? Number(numbered[1]) : null, title, blocks: LegalDocument.blocks(r.lines) };
      });
    return { updated, intro: LegalDocument.blocks(intro), sections };
  }

  private static slug(text: string): string {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "section";
  }

  private static unique(id: string, used: Set<string>): string {
    let candidate = id;
    for (let n = 2; used.has(candidate); n++) candidate = `${id}-${n}`;
    used.add(candidate);
    return candidate;
  }

  /** Text and tables, in the order they come. */
  private static blocks(lines: string[]): Block[] {
    const blocks: Block[] = [];
    let text: string[] = [];
    const flush = () => {
      const markdown = text.join("\n").trim();
      if (markdown) blocks.push({ kind: "text", markdown });
      text = [];
    };
    for (let i = 0; i < lines.length; i++) {
      if (!lines[i].trimStart().startsWith("|")) {
        text.push(lines[i]);
        continue;
      }
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trimStart().startsWith("|")) rows.push(LegalDocument.cells(lines[i++]));
      i--;
      flush();
      const [headers, ...rest] = rows;
      blocks.push({ kind: "table", headers, rows: rest.filter((row) => !row.every((cell) => /^:?-+:?$/.test(cell))) });
    }
    flush();
    return blocks;
  }

  private static cells(line: string): string[] {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  }
}
