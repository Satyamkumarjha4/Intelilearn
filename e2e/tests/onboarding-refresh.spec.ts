/**
 * A refresh on the last step of the setup. The profile is saved at step 4, which makes the learner "onboarded" to the
 * route guard; the guard used to send a refresh on step 5 to the lesson list and the chosen topic was lost.
 */
import { expect, test } from "@playwright/test";

import { E2E } from "../support/config";
import { Onboarding } from "../support/onboarding";

test("refreshing on the last step stays on it, and the landing topic is still offered", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Topic").fill("Plate tectonics");
  await page.getByLabel("Topic").press("Enter");
  await page.waitForURL(/\/auth/);
  await page.getByLabel("Name").fill("Refresh Tester");
  await page.getByLabel("Email").fill(E2E.email("refresh"));
  await page.getByLabel("Password", { exact: true }).fill(E2E.PASSWORD);
  await page.locator("input[name=accept_terms]").check();
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/onboarding/);
  await new Onboarding(page).throughStepFour();

  await page.reload();

  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByRole("radiogroup", { name: "Topics picked for you" })).toBeVisible();
  await expect(page.getByRole("textbox").first()).toHaveValue(/Plate tectonics/);

  // Finishing ends the setup: from then on /onboarding is not for them any more.
  await new Onboarding(page).startFirstLesson();
  await page.goto("/onboarding");
  await expect(page).toHaveURL(/\/lessons$/);
});
