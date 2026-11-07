import type { ConsolePrice } from "./types";

export type PriceBoxes = { credits: string; label: string };
export type PriceDraft = Record<string, PriceBoxes>;
export type PriceChange = { key: string; body: { credits: number; label?: string } };

/** The price table being edited: the live price and the words on the learner's quote line, per key. */
export class PriceForm {
  static readonly LABEL_MAX = 120;

  static from(prices: readonly ConsolePrice[]): PriceDraft {
    return Object.fromEntries(prices.map((price) => [price.key, { credits: price.credits === null ? "" : String(price.credits), label: price.label }]));
  }

  /** Which keys have been edited: the price or the words differ from what is saved. A key with no live price is only
   *  edited by giving it one. */
  static dirty(prices: readonly ConsolePrice[], draft: PriceDraft): string[] {
    return prices.filter((price) => draft[price.key] && PriceForm.changed(price, draft[price.key])).map((price) => price.key);
  }

  /** What is wrong with each edited row: the price must be a whole number of credits (0 is a price) and the words must
   *  say something and fit. Rows that were not edited are not judged. */
  static errors(prices: readonly ConsolePrice[], draft: PriceDraft): Record<string, { credits?: string; label?: string }> {
    const found: Record<string, { credits?: string; label?: string }> = {};
    for (const price of prices) {
      const boxes = draft[price.key];
      if (!boxes || !PriceForm.changed(price, boxes)) continue;
      const problems: { credits?: string; label?: string } = {};
      if (!/^\d{1,6}$/.test(boxes.credits.trim())) problems.credits = "Enter a whole number of credits (0 is allowed).";
      const label = boxes.label.trim();
      if (!label) problems.label = "Say what this line is called.";
      else if (label.length > PriceForm.LABEL_MAX) problems.label = `At most ${PriceForm.LABEL_MAX} characters.`;
      if (problems.credits || problems.label) found[price.key] = problems;
    }
    return found;
  }

  /** The edits to send, one per changed row. The words are sent only when they changed. */
  static changes(prices: readonly ConsolePrice[], draft: PriceDraft): PriceChange[] {
    return PriceForm.dirty(prices, draft).flatMap((key) => {
      const price = prices.find((candidate) => candidate.key === key)!;
      const boxes = draft[key];
      if (!/^\d{1,6}$/.test(boxes.credits.trim())) return [];
      const body: PriceChange["body"] = { credits: Number(boxes.credits.trim()) };
      if (boxes.label.trim() !== price.label) body.label = boxes.label.trim();
      return [{ key, body }];
    });
  }

  private static changed(price: ConsolePrice, boxes: PriceBoxes): boolean {
    const credits = price.credits === null ? "" : String(price.credits);
    return boxes.credits.trim() !== credits || boxes.label.trim() !== price.label;
  }
}
