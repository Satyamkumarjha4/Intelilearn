import type { Page } from "@playwright/test";

import { Deck } from "./deck";

/** Takes an attempt at the lesson test the way a learner does. The fake model writes every question the same way, so a
 *  test can pick right or wrong answers on purpose and know the score: the right option of a choice question starts with
 *  "Right", a multiple-select question has two right options, and a numerical answer is the number in "question number N". */
export class AttemptPage {
  readonly deck: Deck;

  constructor(private readonly page: Page) {
    this.deck = new Deck(page);
  }

  /** Answers every card with right or wrong answers and hands the attempt in. Returns the number of cards. */
  async answerAll(mode: "right" | "wrong"): Promise<number> {
    await this.deck.next.waitFor({ timeout: 120_000 });
    let cards = 0;
    for (let guard = 0; guard < 40; guard++) {
      await this.page.waitForTimeout(450); // the card flies out
      await this.answerCard(mode);
      const label = await this.deck.next.innerText();
      await this.deck.next.click();
      cards++;
      if (/hand in/i.test(label)) break;
    }
    const confirm = this.page.getByRole("dialog");
    await confirm.waitFor();
    await confirm.getByRole("button", { name: /hand it in/i }).click();
    return cards;
  }

  /** A result can come with a pop-up offering a follow-up lesson. A learner who does not want it turns it down; so do tests
   *  that are about something else. Waits briefly, because the result is read from the server after the hand-in. */
  async dismissOffer(): Promise<void> {
    const dialog = this.page.getByRole("dialog");
    if (await dialog.waitFor({ timeout: 8_000 }).then(() => true, () => false)) {
      await dialog.getByRole("button", { name: "Not now" }).click();
      await dialog.waitFor({ state: "detached" });
    }
  }

  private async answerCard(mode: "right" | "wrong"): Promise<void> {
    const radios = this.page.getByRole("radiogroup", { name: "Answers" }).getByRole("radio");
    const boxes = this.page.getByRole("group", { name: "Answers" }).getByRole("checkbox");
    const right = mode === "right";
    if (await radios.count()) {
      await (right ? radios.filter({ hasText: /Right/ }) : radios.filter({ hasText: /Wrong/ })).first().click();
    } else if (await boxes.count()) {
      const picks = right ? boxes.filter({ hasText: /Right/ }) : boxes.filter({ hasText: /Wrong/ });
      for (let n = 0; n < (await picks.count()); n++) await picks.nth(n).click();
      if (!right && (await picks.count()) > 1) await picks.nth(1).click(); // one wrong option is enough
    } else {
      const text = await this.page.getByText(/question number \d+ in set/).first().innerText();
      await this.page.getByRole("textbox").first().fill(right ? (text.match(/question number (\d+)/)?.[1] ?? "0") : "9999");
    }
  }
}
