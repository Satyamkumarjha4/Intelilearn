/**
 * Unit under test: `SandboxMessages`, `HarnessBuilder`, `RenderMessage`, `SetPageMessage`, `RepairReport` and `RepairGate`, the page's side
 * of the conversation with the lesson iframe.
 *
 * Why: the iframe runs generated code, so everything it posts is untrusted and every address it uses must be absolute
 * (its origin is opaque). A message from any other window, or a malformed one, must never reach the page's logic; a
 * crash must reach the repair endpoint once, not once per error it raises; and a repair that the server refuses must
 * not be asked for again.
 *
 * Use cases:
 * - parses ready, rendered, height, error, pages, page_changed and test_submit messages, and fills in what an error leaves out
 * - drops anything that is not a known message, and a test_submit without answers
 * - accepts a message only from the iframe that was embedded
 * - fills the harness with the runtime's absolute addresses, in every place they occur
 * - makes media URLs absolute without changing the rest of the document
 * - loads the harness once, and tries again after a failure
 * - builds the render message from the document and the theme, hiding the test page of an older lesson
 * - builds the message that opens a page
 * - names the interactive in the repair report, cuts long fields, and leaves out what is missing
 * - asks for a repair once per code version, ignores errors from other versions, and stops when told to
 */
import { describe, expect, test } from "bun:test";

import { HarnessBuilder, HarnessSource, RenderMessage, RepairGate, RepairReport, SandboxMessages, SetPageMessage, type SandboxError } from "./sandbox-bridge";
import type { LessonDocument } from "./types";

const error = (over: Partial<SandboxError> = {}): SandboxError => ({
  phase: "runtime",
  message: "boom",
  stack: "at x",
  codeVersion: 2,
  ...over,
});

const document: LessonDocument = {
  code: "CODE",
  code_version: 2,
  has_embedded_test: false,
  data: {
    title: "T",
    media: {
      a: { url: "/api/media/a?exp=1&sig=x", kind: "image", alt: "", caption: "", attribution: "", license: "", source_url: "", width: 1, height: 1 },
    },
  },
};

describe("SandboxMessages.parse", () => {
  test("reads the messages the runtime posts", () => {
    expect(SandboxMessages.parse({ type: "ready" })).toEqual({ type: "ready" });
    expect(SandboxMessages.parse({ type: "rendered", codeVersion: 2, height: 640 })).toEqual({ type: "rendered", codeVersion: 2, height: 640 });
    expect(SandboxMessages.parse({ type: "height", height: 900 })).toEqual({ type: "height", height: 900 });
    expect(SandboxMessages.parse({ type: "test_submit", answers: { t1: 2 } })).toEqual({ type: "test_submit", answers: { t1: 2 } });
    expect(
      SandboxMessages.parse({ type: "error", phase: "transform", message: "bad", stack: "s", codeVersion: 3, component: "Interactive_x", page: "core" }),
    ).toEqual({ type: "error", error: { phase: "transform", message: "bad", stack: "s", codeVersion: 3, component: "Interactive_x", page: "core" } });
  });

  test("reads which pages the document has and which one is open", () => {
    expect(SandboxMessages.parse({ type: "pages", count: 3, titles: ["A", "B", "C"] })).toEqual({ type: "pages", count: 3, titles: ["A", "B", "C"] });
    expect(SandboxMessages.parse({ type: "page_changed", index: 1 })).toEqual({ type: "page_changed", index: 1 });
  });

  test("keeps only titles that are text, and a missing list is empty", () => {
    expect(SandboxMessages.parse({ type: "pages", count: 2, titles: ["A", 4, null] })).toEqual({ type: "pages", count: 2, titles: ["A"] });
    expect(SandboxMessages.parse({ type: "pages", count: "x" })).toEqual({ type: "pages", count: 0, titles: [] });
    expect(SandboxMessages.parse({ type: "page_changed", index: "2" })).toEqual({ type: "page_changed", index: 0 });
  });

  test("fills in what an error leaves out", () => {
    expect(SandboxMessages.parse({ type: "error" })).toEqual({
      type: "error",
      error: { phase: "runtime", message: "Unknown error", stack: "", codeVersion: 0 },
    });
  });

  test("makes a number of anything that is not one", () => {
    expect(SandboxMessages.parse({ type: "height", height: "tall" })).toEqual({ type: "height", height: 0 });
    expect(SandboxMessages.parse({ type: "height", height: Number.NaN })).toEqual({ type: "height", height: 0 });
  });

  const junk: unknown[] = [null, undefined, "ready", 4, [], {}, { type: "nope" }, { type: 4 }, { type: "test_submit" }, { type: "test_submit", answers: [] }];
  test.each(junk.map((data) => [data]))("drops %p", (data) => {
    expect(SandboxMessages.parse(data)).toBeNull();
  });
});

describe("SandboxMessages.from", () => {
  test("accepts a message only from the embedded iframe", () => {
    const frame = {};

    expect(SandboxMessages.from({ source: frame, data: { type: "ready" } }, frame)).toEqual({ type: "ready" });
    expect(SandboxMessages.from({ source: {}, data: { type: "ready" } }, frame)).toBeNull();
    expect(SandboxMessages.from({ source: null, data: { type: "ready" } }, null)).toBeNull();
  });
});

describe("HarnessBuilder", () => {
  const template = [
    "script-src __ASSETS__ 'unsafe-eval'; style-src __ASSETS__; img-src __MEDIA__ data:",
    '<link href="__RUNTIME_CSS__"><script src="__TAILWIND__"></script><script src="__RUNTIME__"></script>',
  ].join("\n");

  test("fills the policy and the asset addresses with absolute ones", () => {
    const html = new HarnessBuilder("https://learn.example").html(template);

    expect(html).toContain("script-src https://learn.example 'unsafe-eval'; style-src https://learn.example; img-src https://learn.example data:");
    expect(html).toContain('href="https://learn.example/sandbox/runtime.css"');
    expect(html).toContain('src="https://learn.example/sandbox/tailwind.js"');
    expect(html).toContain('src="https://learn.example/sandbox/runtime.js"');
    expect(html).not.toContain("__");
  });

  test("makes media URLs absolute and leaves the rest of the document alone", () => {
    const result = new HarnessBuilder("https://learn.example").absolute(document);

    expect(result.data.media.a.url).toBe("https://learn.example/api/media/a?exp=1&sig=x");
    expect(result.data.title).toBe("T");
    expect(result.code).toBe("CODE");
    expect(document.data.media.a.url).toBe("/api/media/a?exp=1&sig=x");
  });

  test("keeps an absolute media URL as it is, and copes with a document without media", () => {
    const builder = new HarnessBuilder("https://learn.example");
    const absolute = { ...document, data: { media: { a: { ...document.data.media.a, url: "https://cdn.example/a.png" } } } };

    expect(builder.absolute(absolute).data.media.a.url).toBe("https://cdn.example/a.png");
    expect(builder.absolute({ ...document, data: {} as LessonDocument["data"] }).data.media).toEqual({});
  });
});

describe("HarnessSource", () => {
  const reply = (ok: boolean, body = "<html>") => async () => ({ ok, text: async () => body });

  test("fetches the harness once and shares it", async () => {
    let fetches = 0;
    const source = new HarnessSource(async () => {
      fetches += 1;
      return { ok: true, text: async () => "<html>" };
    });

    const [first, second] = await Promise.all([source.load(), source.load()]);

    expect([first, second, fetches]).toEqual(["<html>", "<html>", 1]);
  });

  test("does not remember a failure, so the next try can succeed", async () => {
    let ok = false;
    const source = new HarnessSource(async () => reply(ok)());

    await expect(source.load()).rejects.toThrow("could not be loaded");
    ok = true;

    expect(await source.load()).toBe("<html>");
  });
});

describe("RenderMessage", () => {
  test("carries the code, the data, the version and the theme", () => {
    expect(RenderMessage.of(document, "dark")).toEqual({ type: "render", code: "CODE", data: document.data, codeVersion: 2, theme: "dark", hide: [] });
  });

  test("hides the test page of a lesson that still has it in its code", () => {
    expect(RenderMessage.of({ ...document, has_embedded_test: true }, "light").hide).toEqual(["test"]);
  });
});

describe("SetPageMessage", () => {
  test("opens the page at an index", () => {
    expect(SetPageMessage.of(2)).toEqual({ type: "set_page", index: 2 });
  });
});

describe("RepairReport", () => {
  test("names the interactive that crashed so the server can find it", () => {
    expect(RepairReport.of(error({ component: "Interactive_x", page: "core" }))).toEqual({
      message: "Interactive_x crashed: boom",
      stack: "at x",
      page: "core",
    });
  });

  test("leaves out the stack and the page when there are none", () => {
    expect(RepairReport.of(error({ stack: "" }))).toEqual({ message: "boom" });
  });

  test("cuts fields to what the server accepts", () => {
    const report = RepairReport.of(error({ message: "m".repeat(3000), stack: "s".repeat(9000), page: "p".repeat(40) }));

    expect([report.message.length, report.stack?.length, report.page?.length]).toEqual([2000, 8000, 20]);
  });
});

describe("RepairGate", () => {
  test("asks once per code version, however many errors the crash raises", () => {
    const gate = new RepairGate();

    expect([gate.shouldRepair(error(), 2), gate.shouldRepair(error({ message: "again" }), 2)]).toEqual([true, false]);
    expect(gate.shouldRepair(error({ codeVersion: 3 }), 3)).toBe(true);
  });

  test("ignores an error from a version the page has moved past", () => {
    const gate = new RepairGate();

    expect(gate.shouldRepair(error({ codeVersion: 1 }), 2)).toBe(false);
    expect(gate.shouldRepair(error({ codeVersion: 2 }), 2)).toBe(true);
  });

  test("stops for good once the server has refused", () => {
    const gate = new RepairGate();
    gate.stop();

    expect([gate.isStopped, gate.shouldRepair(error(), 2)]).toEqual([true, false]);
  });
});
