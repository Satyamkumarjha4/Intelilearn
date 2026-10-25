/**
 * Who may open the staff console: staff do, a learner gets the page that does not exist (and the API the same 404), and
 * someone signed out is asked to sign in first.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";

test("staff open the console; a learner is told it is not there", async ({ browser }) => {
  const learner = await (await browser.newContext()).newPage();
  await new Api(learner).signUp(E2E.email("console"), E2E.PASSWORD);
  await learner.goto("/console");
  await expect(learner.getByText(/couldn.t find that page/i)).toBeVisible();
  expect((await new Api(learner).call("GET", "/console/overview")).status).toBe(404);

  const staff = await (await browser.newContext()).newPage();
  const staffApi = new Api(staff);
  expect((await staffApi.call("POST", "/auth/login", { email: E2E.STAFF_EMAIL, password: E2E.STAFF_PASSWORD })).status).toBe(200);
  await staffApi.call("PUT", "/profile", {
    education_level: "working",
    grade_or_year: "",
    field_of_study: "Operations",
    learning_preference: "mixed",
    goal: "quick_overview",
    preferred_language: "en",
    notes: "",
  });
  await staff.goto("/console/usage?range=30d");
  await expect(staff.getByRole("heading", { name: /usage/i }).first()).toBeVisible();
  await expect(staff).toHaveURL(/range=30d/); // the filter lives in the address
});

test("someone signed out is sent to sign in, then on to the console", async ({ page }) => {
  await page.goto("/console");
  await expect(page).toHaveURL(/\/auth\?next=%2Fconsole/);
});
