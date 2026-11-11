import { expect, type Page } from "@playwright/test";

import { Choose } from "./choose";

/** Answers a card deck (the quick check, or the test) one card at a time, the way a learner does.
 *
 *  The browser runs with reduced motion (`playwright.config.ts`), which the app respects: a card does not fly out, so there is
 *  nothing to wait for but the next card itself, which is the progress count changing. */
export class Deck {
  constructor(private readonly page: Page) {}

  get next() {
    return this.page.locator("[data-deck-continue]");
  }

  /** "3 / 10": which card the deck is on. It changes when the learner continues. */
  get progress() {
    return this.page.getByText(/^\d+ \/ \d+$/).first();
  }

  /** Presses Continue (or the last card's Finish) and waits for the deck to show the next card. Returns the button's label. */
  async advance(): Promise<string> {
    await expect(this.next).toBeEnabled();
    const label = await this.next.innerText();
    const before = await this.progress.innerText();
    await this.next.click();
    if (!/finish|hand in/i.test(label)) await expect(this.progress).not.toHaveText(before);
    return label;
  }

  /** `pick(position, optionTexts)` is an option index, or "dont_know". Returns how many cards were answered. */
  async answerAll(pick: (position: number, options: string[]) => number | "dont_know"): Promise<number> {
    await this.next.waitFor({ timeout: 120_000 });
    let answered = 0;
    for (;;) {
      const group = this.page.getByRole("radiogroup", { name: "Answers" });
      if (!(await group.count())) break;
      const radios = group.first().getByRole("radio");
      const choice = pick(answered, await radios.allInnerTexts());
      await Choose.option(choice === "dont_know" ? this.page.getByRole("radio", { name: /don.t know/i }) : radios.nth(choice));
      const label = await this.advance();
      answered++;
      if (/finish/i.test(label)) break;
    }
    return answered;
  }

  /** Every card answered right: a perfect quick check. */
  static readonly allRight = (_position: number, options: string[]) => Math.max(0, options.findIndex((text) => /true statement/.test(text)));

  /** The fake model writes the right option as "The true statement about idea N". */
  static readonly rightOrDontKnow = (position: number, options: string[]) =>
    position % 2 === 0 ? Math.max(0, options.findIndex((text) => /true statement/.test(text))) : ("dont_know" as const);
}
