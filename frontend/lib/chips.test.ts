/**
 * Unit under test: `Chips`, how the topic chips of "Your starting point" are shown: in sentence case, and no more than
 * a handful until the learner asks for the rest.
 *
 * Why: the assessment can list a dozen concepts, in whatever capitals a model chose. Twelve chips make a card very
 * long and Title Case Shouting makes it noisy, but flattening "DFS" or "JavaScript" to lower case would be wrong.
 *
 * Use cases:
 * - text is shown in sentence case: the first letter up, other words down
 * - words that are acronyms, have digits, or carry their own capitals ("DFS", "O(n)", "JavaScript", "pH") stay as they are
 * - the stored data is not touched
 * - up to the limit all chips show; past it the rest are hidden behind a "+N more" until expanded
 * - a long list can be opened and closed again (so the button stays and says which it will do); a short one has no button
 * - a list one over the limit still collapses (one chip hidden is not worth a button, so it shows), and an empty list is empty
 */
import { describe, expect, test } from "bun:test";

import { Chips } from "./chips";

describe("sentence", () => {
  test.each([
    ["Binary Search Tree", "Binary search tree"],
    ["HALVING THE RANGE", "Halving the range"],
    ["the loop invariant", "The loop invariant"],
    ["Depth-First Search (DFS)", "Depth-first search (DFS)"],
    ["Big O notation", "Big O notation"],
    ["Time Complexity O(n log n)", "Time complexity O(n log n)"],
    ["Using JavaScript Arrays", "Using JavaScript arrays"],
    ["Measuring pH Levels", "Measuring pH levels"],
    ["Newton's Second Law", "Newton's second law"],
    ["  spaced   out  ", "Spaced out"],
    ["", ""],
  ])("%j reads %j", (input, shown) => {
    expect(Chips.sentence(input)).toBe(shown);
  });

  test("does not change what it is given", () => {
    const data = ["Binary Search"];
    Chips.sentence(data[0]);

    expect(data).toEqual(["Binary Search"]);
  });
});

describe("collapse", () => {
  const items = Array.from({ length: 12 }, (_, n) => `Topic ${n}`);

  test("shows the first six and counts the rest", () => {
    const view = Chips.collapse(items, 6, false);

    expect(view.shown).toEqual(items.slice(0, 6));
    expect(view.hidden).toBe(6);
  });

  test("shows everything when expanded", () => {
    expect(Chips.collapse(items, 6, true)).toEqual({ shown: items, hidden: 0 });
  });

  test("shows everything when there are no more than the limit", () => {
    expect(Chips.collapse(items.slice(0, 6), 6, false)).toEqual({ shown: items.slice(0, 6), hidden: 0 });
    expect(Chips.collapse([], 6, false)).toEqual({ shown: [], hidden: 0 });
  });

  test("one chip over the limit is shown too, since a button for one is no saving", () => {
    expect(Chips.collapse(items.slice(0, 7), 6, false)).toEqual({ shown: items.slice(0, 7), hidden: 0 });
  });
});

describe("collapsible", () => {
  test("only a list longer than the limit plus one has something to open", () => {
    expect(Chips.collapsible(Array.from({ length: 8 }, String), 6)).toBe(true);
    expect(Chips.collapsible(Array.from({ length: 7 }, String), 6)).toBe(false);
    expect(Chips.collapsible([], 6)).toBe(false);
  });
});
