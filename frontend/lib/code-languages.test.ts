/**
 * Unit under test: `CodeLanguages`, which language pack the code editor loads for a question.
 *
 * Why: a short or long answer about code names its language in the model's own words, and the editor loads one pack per
 * language, on demand. A name read too strictly would leave a Python question without colours; a pack loaded for a name
 * that has none would break the editor. A keyboard user is also told how to leave the editor, because Tab indents inside it.
 *
 * Use cases:
 * - reads a language's name leniently: any case, a version number after it, spaces, and the usual short names
 * - falls back to plain code (an editor with no colours) for a language with no pack and for no name at all
 * - labels each language for a screen reader
 * - has the hint that says how to leave the editor with the keyboard
 */
import { describe, expect, test } from "bun:test";

import { CodeLanguages } from "./code-languages";

describe("reading a name", () => {
  test.each([
    ["python", "python"], ["Python", "python"], ["Python 3", "python"], ["python3.12", "python"], ["py", "python"],
    ["JavaScript", "javascript"], ["js", "javascript"], ["Node", "javascript"],
    ["TypeScript", "typescript"], ["ts", "typescript"],
    ["Java", "java"], ["C++", "cpp"], ["c", "cpp"], ["cpp", "cpp"], ["  C ++ ", "cpp"],
  ] as const)("%p is read as %p", (name, key) => {
    expect(CodeLanguages.of(name)).toBe(key);
  });

  test.each(["", "  ", "Rust", "C#", "pseudocode", null, undefined])("%p has no pack, so it is plain code", (name) => {
    expect(CodeLanguages.of(name)).toBe("plain");
  });
});

describe("the words", () => {
  test("a label for each language", () => {
    expect(CodeLanguages.label("py")).toBe("Python");
    expect(CodeLanguages.label("c++")).toBe("C++");
    expect(CodeLanguages.label("Rust")).toBe("Code");
  });

  test("the hint says how to leave", () => {
    expect(CodeLanguages.LEAVE_HINT).toBe("Press Esc then Tab to leave the editor.");
  });
});
