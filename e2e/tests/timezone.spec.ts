/**
 * The learner's time zone (credits plan D9). Sign-up sends the browser's zone without starting the lock; the profile page
 * shows it, lets the learner change it once, and then says when it can be changed again. The server refuses a second
 * change inside the 30 days whatever the page does.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Outbox } from "../support/outbox";

test.use({ timezoneId: "Europe/London" });

const PROFILE = {
  education_level: "school",
  grade_or_year: "9",
  field_of_study: "",
  learning_preference: "mixed",
  goal: "exam_prep",
  preferred_language: "en",
  notes: "",
};

test("sign-up keeps the browser's zone, the profile changes it once, and then it is locked", async ({ page }) => {
  await page.goto("/auth?mode=register");
  await page.getByLabel("Name").fill("Zone Tester");
  const email = E2E.email("zone");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(E2E.PASSWORD);
  await page.locator("input[name=accept_terms]").check();
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/auth\/verify/);
  await page.getByLabel("6-digit code").fill(await Outbox.code(page.request, email));
  await page.waitForURL(/\/onboarding/);

  const api = new Api(page);
  const first = await api.call("GET", "/profile");
  expect(first.body).toMatchObject({ timezone: "Europe/London", effective_timezone: "Europe/London", timezone_locked_until: null });
  expect((await api.call("PUT", "/profile", PROFILE)).status).toBe(200);

  await page.goto("/profile");
  const zone = page.getByLabel("Time zone");
  await expect(zone).toHaveValue("Europe/London");
  await expect(page.getByText("You can change this once every 30 days.")).toBeVisible();

  await zone.fill("Asia/Tokyo");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Profile saved")).toBeVisible();
  await expect(zone).toBeDisabled();
  await expect(page.getByText(/You can change your time zone again on \d+ \w+ \d{4}\./)).toBeVisible();

  const refused = await api.call("PATCH", "/profile", { timezone: "America/New_York" });
  expect(refused.status).toBe(409);
  expect(refused.body).toMatchObject({ code: "timezone_locked" });
  expect((await api.call("GET", "/profile")).body.timezone).toBe("Asia/Tokyo");
});
