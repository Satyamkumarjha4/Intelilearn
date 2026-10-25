/**
 * Unit under test: `PlainWarning`, which rewrites the notes the lesson builder leaves (they are written for developers)
 * in words a learner can read.
 *
 * Why: the "Small notes" on the building screen are shown to school and college students. Words like "sandbox", "model",
 * "node" or a code error in them are noise at best and alarming at worst, and an unknown note must never leak through.
 *
 * Use cases:
 * - each kind of note the builder writes becomes one calm sentence without technical words
 * - a note that is not recognised becomes a generic sentence, never the original text
 * - a list of notes is rewritten, with repeats shown once
 * - the reason a lesson failed is told plainly: stopped, helper unavailable, quality checks, busy, or a generic line
 * - the reason a saved version of the lesson exists is told plainly too: a repair never shows the page's error text
 */
import { describe, expect, test } from "bun:test";

import { PlainError, PlainVersion, PlainWarning } from "./plain-notes";

const TECHNICAL = /model|node|sandbox|llm|graph|pipeline|stage|code|tsx|run\b/i;

describe("PlainWarning.of", () => {
  test.each([
    "The quiz review was skipped: none of its models answered.",
    "The quiz reviewer still had concerns: a; b",
    'The picture "Amoeba" could not be checked by the vision model and is shown unchecked.',
    "The core page uses the standard layout: generated code kept failing (line 3:0 [syntax] x)",
    "Pages use the standard layout: the generated pages clashed",
    "The advanced page uses the standard layout after a failed repair",
    'Dropped the interactive "widget_core" after a failed repair',
    'Dropped the interactive "widget_core": it kept failing the code checks',
    "Interactive plan kept 3 of 5 items (2 invalid)",
    'No suitable image found for "widget_intro": drawing an SVG diagram instead',
    'Could not find better media for "widget_intro"',
    "The final test was kept despite: Too few questions",
    "Could not apply the review fix to the core page: boom",
  ])("%s becomes a plain sentence", (message) => {
    const plain = PlainWarning.of(message);

    expect(plain).toMatch(/^[A-Z].*\.$/);
    expect(plain).not.toMatch(TECHNICAL);
    expect(plain).not.toContain(message);
  });

  test("a note that is not recognised becomes a generic sentence", () => {
    expect(PlainWarning.of("KeyError: 'x' in render_check")).toBe("One small thing needed a workaround.");
  });
});

describe("PlainWarning.all", () => {
  test("rewrites every note and shows repeats once", () => {
    const notes = PlainWarning.all([
      "The core page uses the standard layout: a",
      "The advanced page uses the standard layout: b",
      "Interactive plan kept 3 of 5 items (2 invalid)",
    ]);

    expect(notes).toHaveLength(2);
  });

  test("no notes, no list", () => {
    expect(PlainWarning.all([])).toEqual([]);
  });
});

describe("PlainError.of", () => {
  test.each([
    ["Cancelled. Press Retry to continue where it stopped.", "stopped"],
    ["The background worker queue is unreachable. Nothing was lost: try again in a moment.", "helper"],
    ["The lesson failed the sandbox render check: Runtime error", "quality checks"],
    ["The lesson document does not pass the code checks: line 1:0 [syntax] x", "quality checks"],
    ["Every AI model failed for lesson.plan: 429 rate limit", "busy or unavailable"],
    ["No AI model is bound to 'diagnostic.generate'. An admin must bind one in the model registry first.", "busy or unavailable"],
  ])("%s", (message, gist) => {
    const plain = PlainError.of(message);

    expect(plain).toContain(gist);
    expect(plain).not.toMatch(TECHNICAL);
  });

  test("anything else is a generic, blame-free line", () => {
    expect(PlainError.of("KeyError: 'plan'")).toBe(PlainError.FALLBACK);
    expect(PlainError.of("")).toBe(PlainError.FALLBACK);
  });
});

describe("PlainVersion.of", () => {
  test("a repair is a fixed glitch, whatever error the page threw", () => {
    const plain = PlainVersion.of("Runtime repair: TypeError: Cannot read properties of undefined (reading 'map')");

    expect(plain).toBe("Fixed a glitch on a page");
    expect(plain).not.toMatch(/TypeError|undefined|map/);
  });

  test("going back keeps its number", () => {
    expect(PlainVersion.of("Before going back to version 2")).toBe("Saved before going back to version 2");
  });

  test("a reason that is empty or not recognised is an earlier version, never the original text", () => {
    expect(PlainVersion.of("")).toBe(PlainVersion.FALLBACK);
    expect(PlainVersion.of("graph node patch_page failed")).toBe(PlainVersion.FALLBACK);
  });
});
