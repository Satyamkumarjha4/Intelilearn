/**
 * Unit under test: `CheatGroups`, how the items of one cheat-sheet section are laid out in its box.
 *
 * Why: the generated sheet mixes formulas, rules and terms in one list, but the page shows each kind its own way
 * (formulas in a muted box, terms as a definition list, the rest as plain points). Nothing the sheet says may be
 * dropped on the way, and the order the author wrote them in is kept inside each group.
 *
 * Use cases:
 * - an item with a formula, or of kind "formula", is a formula, even when its kind says something else
 * - an item of kind "term" without a formula is a term
 * - rules, facts and patterns are plain points
 * - every item lands in exactly one group, in the order it was written
 * - an empty section has no groups
 */
import { describe, expect, test } from "bun:test";

import { CheatGroups } from "./cheat-groups";
import type { CheatItem } from "./types";

const item = (label: string, over: Partial<CheatItem> = {}): CheatItem => ({
  label,
  kind: "rule",
  content: "",
  formula: "",
  variables: [],
  when_to_use: "",
  ...over,
});

describe("CheatGroups.of", () => {
  test("an item with a formula is a formula whatever its kind", () => {
    const groups = CheatGroups.of([item("a", { kind: "rule", formula: "x^2" }), item("b", { kind: "formula" })]);
    expect(groups.formulas.map((i) => i.label)).toEqual(["a", "b"]);
  });

  test("a term without a formula is a term", () => {
    expect(CheatGroups.of([item("t", { kind: "term" })]).terms.map((i) => i.label)).toEqual(["t"]);
  });

  test.each(["rule", "fact", "pattern"] as const)("a %s is a plain point", (kind) => {
    expect(CheatGroups.of([item("p", { kind })]).points.map((i) => i.label)).toEqual(["p"]);
  });

  test("every item lands in one group and keeps the order it was written in", () => {
    const groups = CheatGroups.of([
      item("1", { kind: "term" }),
      item("2", { kind: "formula" }),
      item("3", { kind: "fact" }),
      item("4", { kind: "term" }),
      item("5", { kind: "rule" }),
    ]);
    expect(groups.terms.map((i) => i.label)).toEqual(["1", "4"]);
    expect(groups.formulas.map((i) => i.label)).toEqual(["2"]);
    expect(groups.points.map((i) => i.label)).toEqual(["3", "5"]);
  });

  test("an empty section has no groups", () => {
    expect(CheatGroups.of([])).toEqual({ formulas: [], terms: [], points: [] });
  });
});
