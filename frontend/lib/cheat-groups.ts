import type { CheatItem } from "@/lib/types";

export type CheatGroup = { formulas: CheatItem[]; terms: CheatItem[]; points: CheatItem[] };

/** Splits one section of a cheat sheet by how each kind of item is shown: formulas, terms, and plain points. */
export class CheatGroups {
  static of(items: CheatItem[]): CheatGroup {
    const isFormula = (item: CheatItem) => item.kind === "formula" || item.formula !== "";
    return {
      formulas: items.filter(isFormula),
      terms: items.filter((item) => !isFormula(item) && item.kind === "term"),
      points: items.filter((item) => !isFormula(item) && item.kind !== "term"),
    };
  }
}
