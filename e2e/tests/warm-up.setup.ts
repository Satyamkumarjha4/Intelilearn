/**
 * Not a test of the app: it opens every page once (the landing page and sign-in signed out, the rest as a learner, the
 * console as staff) before any spec runs.
 *
 * The stack runs `next dev`, which compiles a route the first time it is opened and then reloads the pages other workers
 * have open. With the specs running in parallel that reload would land in the middle of someone's quiz. After this, every
 * route is compiled. It also says so, early and plainly, when the dev server is broken (a cold start once answered 500 on
 * every page): the specs behind it do not run, instead of each failing three minutes later.
 */
import { expect, test as setup, type Page } from "@playwright/test";

import { Api } from "../support/api";
import { AppRoutes } from "../support/app-routes";
import { E2E } from "../support/config";

async function open(page: Page, path: string): Promise<void> {
  const response = await page.goto(path, { waitUntil: "load", timeout: 170_000 });
  expect(
    response?.status() ?? 0,
    `${path} answered an error: the frontend's dev server is broken (try \`make e2e-down\`, then \`make fake-llm\`)`,
  ).toBeLessThan(500);
}

setup("every page of the app is compiled before the specs run", async ({ browser }) => {
  setup.setTimeout(600_000);
  const routes = AppRoutes.discover();
  const learnerRoutes = routes.filter((path) => !AppRoutes.isConsole(path));

  const signedOut = await (await browser.newContext()).newPage();
  for (const path of routes.filter(AppRoutes.isSignedOutOnly)) await open(signedOut, path); // the rest redirect a signed-out visit

  const learner = await (await browser.newContext()).newPage();
  await new Api(learner).signUp(E2E.email("warm-up"), E2E.PASSWORD);
  for (const path of learnerRoutes) await open(learner, path);

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
  for (const path of routes.filter(AppRoutes.isConsole)) await open(staff, path);
});
