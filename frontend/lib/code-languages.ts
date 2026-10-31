/** The language packs the code editor can load, by a key that names the pack. `plain` has no pack: no colours, still an editor. */
export type CodeLanguage = "python" | "javascript" | "typescript" | "java" | "cpp" | "plain";

const ALIASES: Record<string, CodeLanguage> = {
  python: "python", python3: "python", py: "python",
  javascript: "javascript", js: "javascript", node: "javascript", jsx: "javascript",
  typescript: "typescript", ts: "typescript", tsx: "typescript",
  java: "java",
  cpp: "cpp", "c++": "cpp", c: "cpp", "c#": "plain", cc: "cpp", cxx: "cpp",
};

/**
 * Which language pack a question's `language` needs. The model names the language in its own words ("Python 3", "C++",
 * "js"), so the name is read leniently; a language with no pack is still an editor, without colours. Packs are loaded one
 * at a time, when a question asks for them, so a page without code questions never downloads one.
 */
export class CodeLanguages {
  static readonly LABELS: Record<CodeLanguage, string> = {
    python: "Python", javascript: "JavaScript", typescript: "TypeScript", java: "Java", cpp: "C++", plain: "Code",
  };

  static of(name: string | null | undefined): CodeLanguage {
    const key = (name ?? "").trim().toLowerCase().replace(/[\s_-]*v?\d[\d.]*$/, "").replace(/\s+/g, "");
    return ALIASES[key] ?? "plain";
  }

  static label(name: string | null | undefined): string {
    return CodeLanguages.LABELS[CodeLanguages.of(name)];
  }

  /** The line under the editor that tells a keyboard user how to leave it (Tab indents inside, so Tab alone cannot). */
  static readonly LEAVE_HINT = "Press Esc then Tab to leave the editor.";
}
