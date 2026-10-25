/**
 * Unit under test: `Clipboard`, which copies the email address and the subject lines of the Contact page.
 *
 * Why: copying is the fallback for mail links, so it must not fail where mail links fail: on a page without the clipboard
 * API, or when the browser refuses it. It has to say honestly whether it worked, so the page never shows "Copied" when
 * nothing was copied.
 *
 * Use cases:
 * - uses the clipboard API when there is one
 * - falls back to selecting a hidden box and copying, when the API is missing or refuses
 * - says false when neither works (no document, or the copy command fails or throws), and always removes its box
 */
import { describe, expect, test } from "bun:test";

import { Clipboard } from "./clipboard";

function fakeDocument(result: boolean | "throw") {
  const log: string[] = [];
  const box = { value: "", style: {} as Record<string, string>, setAttribute: () => undefined, select: () => log.push("select"), remove: () => log.push("remove") };
  const doc = {
    createElement: () => box,
    body: { appendChild: () => log.push("append") },
    execCommand: () => {
      if (result === "throw") throw new Error("no");
      return result;
    },
  };
  return { doc: doc as never, box, log };
}

describe("copy", () => {
  test("uses the clipboard API when there is one", async () => {
    const written: string[] = [];

    const ok = await new Clipboard({ clipboard: { writeText: async (t) => void written.push(t) } }, null).copy("satyamjha4@gmail.com");

    expect([ok, written]).toEqual([true, ["satyamjha4@gmail.com"]]);
  });

  test.each([
    ["is missing", {}],
    ["refuses", { clipboard: { writeText: async () => Promise.reject(new Error("denied")) } }],
  ])("selects and copies a hidden box when the API %s", async (_, nav) => {
    const { doc, box, log } = fakeDocument(true);

    expect(await new Clipboard(nav, doc).copy("hello")).toBe(true);
    expect(box.value).toBe("hello");
    expect(log).toEqual(["append", "select", "remove"]);
  });

  test("says false when the copy command fails or throws, and still removes its box", async () => {
    for (const result of [false, "throw"] as const) {
      const { doc, log } = fakeDocument(result);

      expect(await new Clipboard({}, doc).copy("x")).toBe(false);
      expect(log.at(-1)).toBe("remove");
    }
  });

  test("says false with nothing to copy with", async () => {
    expect(await new Clipboard({}, null).copy("x")).toBe(false);
  });
});
