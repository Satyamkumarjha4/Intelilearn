import { expect, type Locator } from "@playwright/test";

/**
 * Picks an option of a card and does not move on until the page has taken it.
 *
 * A click made before the page has hydrated is lost without a sound (the server-rendered button is there, and does nothing),
 * and `next dev` under several workers is slow enough for that to happen. A lost pick left the card's Continue disabled, and the
 * test waited three minutes for it. So the click is repeated until the option reports itself chosen (`aria-checked`), and it is
 * never repeated on one that already is, which would un-pick a multiple-select box.
 */
export class Choose {
  static async option(option: Locator, ms = 30_000): Promise<void> {
    await expect(async () => {
      if ((await option.getAttribute("aria-checked")) !== "true") await option.click({ timeout: 5_000 });
      await expect(option).toHaveAttribute("aria-checked", "true", { timeout: 2_000 });
    }).toPass({ timeout: ms });
  }
}
