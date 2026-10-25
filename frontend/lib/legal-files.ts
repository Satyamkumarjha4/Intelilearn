import { readFileSync } from "node:fs";
import { join } from "node:path";

import { LegalDocument, type ParsedLegal } from "@/lib/legal-document";

/** Reads a legal page's copy from `content/legal/<name>.md`. Server only: the pages are drawn on the server. */
export class LegalFiles {
  static read(name: "privacy" | "terms"): ParsedLegal {
    return LegalDocument.parse(readFileSync(join(process.cwd(), "content", "legal", `${name}.md`), "utf8"));
  }
}
