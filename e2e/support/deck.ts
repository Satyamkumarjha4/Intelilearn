import type { Page } from "@playwright/test";

/** Answers a card deck (the quick check, or the test) one card at a time, the way a learner does. */
export class Deck {
  constructor(private readonly page: Page) {}

  get next() {
    return this.page.locator("[data-deck-continue]");
  }

  /** `pick(position, optionTexts)` is an option index, or "dont_know". Returns how many cards were answered. */
  async answerAll(pick: (position: number, options: string[]) => number | "dont_know"): Promise<number> {
    await this.next.waitFor({ timeout: 120_000 });
    let answered = 0;
    for (;;) {
      await this.page.waitForTimeout(450); // the card flies out
      const group = this.page.getByRole("radiogroup", { name: "Answers" });
      if (!(await group.count())) break;
      const radios = group.first().getByRole("radio");
      const choice = pick(answered, await radios.allInnerTexts());
      if (choice === "dont_know") await this.page.getByRole("radio", { name: /don.t know/i }).click();
      else await radios.nth(choice).click();
      const label = await this.next.innerText();
      await this.next.click();
      answered++;
      if (/finish/i.test(label)) break;
    }
    return answered;
  }

  /** The fake model writes the right option as "The true statement about idea N". */
  static readonly rightOrDontKnow = (position: number, options: string[]) =>
    position % 2 === 0 ? Math.max(0, options.findIndex((text) => /true statement/.test(text))) : ("dont_know" as const);
}
