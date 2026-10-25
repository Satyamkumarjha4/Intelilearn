/**
 * The landing page for someone who is not signed in: the try-it question works and a second try shows another one, and
 * nothing meant for the team (API docs, the admin, a system status) is on it.
 */
import { expect, test } from "@playwright/test";

test("the try-it question can be answered and tried again", async ({ page }) => {
  await page.goto("/");
  const options = page.getByRole("group", { name: "Answers" }).first();
  const card = options.locator("xpath=..");
  const first = await card.innerText();

  await options.getByRole("button").first().click();
  const again = page.getByRole("button", { name: /try (again|another)/i });
  await expect(again).toBeVisible();
  await again.first().click();

  await expect(async () => expect(await card.innerText()).not.toBe(first)).toPass({ timeout: 10_000 });
});

test("the page carries nothing for the team and the question is never cached", async ({ page, request }) => {
  const html = await (await request.get("/")).text();
  expect(html).not.toMatch(/api\/docs|\/admin|System status/i);
  const demo = await request.get("/api/landing/demo-question");
  expect(demo.headers()["cache-control"]).toMatch(/no-store/);
  await page.goto("/lessons");
  await expect(page).toHaveURL(/\/auth\?next=%2Flessons/); // signed out: asked to sign in, and told where to go after
});
