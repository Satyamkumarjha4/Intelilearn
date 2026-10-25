import type { Page } from "@playwright/test";

/** The five-step setup, answered the way a learner would (the first tile each time). */
export class Onboarding {
  constructor(private readonly page: Page) {}

  private tiles(label: string) {
    return this.page.getByRole("radiogroup", { name: label }).getByRole("radio");
  }

  /** Steps 1 to 4: the profile is saved when the last Continue is pressed, so step 5 (the topics) is showing after. */
  async throughStepFour(): Promise<void> {
    const page = this.page;
    await this.tiles("Where are you in your studies?").first().click();
    const grade = page.locator('[role=radiogroup][aria-labelledby="grade-question"] [role=radio]');
    if (await grade.count()) await grade.first().click();
    await page.getByRole("button", { name: "Continue" }).click();
    await this.tiles("How do you learn best?").first().click();
    await page.getByRole("button", { name: "Continue" }).click();
    await this.tiles("What's your main goal?").first().click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("radiogroup", { name: "Lesson language" }).waitFor();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("radiogroup", { name: "Topics picked for you" }).waitFor({ timeout: 30_000 });
  }

  /** Picks the first suggested topic and starts the quick check. Resolves with the new lesson's id. */
  async startFirstLesson(): Promise<string> {
    await this.tiles("Topics picked for you").first().click();
    await this.page.getByRole("button", { name: "Start my quick check" }).click();
    await this.page.waitForURL(/\/lessons\/[0-9a-f-]{36}/, { waitUntil: "commit" });
    return /\/lessons\/([0-9a-f-]{36})/.exec(this.page.url())![1]!;
  }
}
