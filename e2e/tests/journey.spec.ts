/**
 * The learner's whole path, in a browser, against the fake model: the landing page's question, sign-up with consent,
 * the five-step setup, a suggested topic, a forward-only quick check, the lesson book, a test that can be submitted
 * once, its read-only results, and a second submission refused by the API.
 *
 * Why: each screen is unit-tested, but the seams (the cookie after sign-up, the guard's redirects, a run that builds
 * while the page polls, a test that must not be answerable twice) only show in the browser.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";
import { Onboarding } from "../support/onboarding";

test("a learner signs up, learns, takes the test once and cannot take it again", async ({ page }) => {
  const api = new Api(page);

  // The topic typed on the landing page survives sign-up, and consent is required.
  await page.goto("/");
  await page.getByLabel("Topic").fill("Photosynthesis");
  await page.getByLabel("Topic").press("Enter");
  await page.waitForURL(/\/auth/);
  await page.getByLabel("Name").fill("E2E Learner");
  await page.getByLabel("Email").fill(E2E.email("journey"));
  await page.getByLabel("Password", { exact: true }).fill(E2E.PASSWORD);
  await page.locator("form button[type=submit]").click();
  await expect(page.locator("#accept_terms-error")).toBeVisible(); // not without agreeing to the terms
  await page.locator("input[name=accept_terms]").check();
  await page.locator("form button[type=submit]").click();
  await page.waitForURL(/\/onboarding/);

  const setup = new Onboarding(page);
  await setup.throughStepFour();
  await expect(page.getByRole("textbox").first()).toHaveValue(/Photosynthesis/); // the landing topic is offered
  const lessonId = await setup.startFirstLesson();

  // The quick check goes forward only: no Back, and Continue waits for an answer.
  const deck = new Deck(page);
  await expect(deck.next).toBeDisabled();
  await expect(page.getByRole("button", { name: /^(← )?(back|previous)/i })).toHaveCount(0);
  expect(await deck.answerAll(Deck.rightOrDontKnow)).toBe(10);

  await api.until(lessonId, (lesson) => lesson.stage === "ready");
  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByText(/Page 1 of 3/).first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "More" }).click();
  await expect(page.getByRole("menuitem", { name: "Reload this lesson" })).toBeVisible();
  await page.keyboard.press("Escape");

  // The test: answer every card, confirm, and the marks stay read-only.
  await page.goto(`/lessons/${lessonId}?tab=test`);
  const testDeck = new Deck(page);
  const start = page.getByRole("button", { name: /start|begin|take the test/i });
  await start.or(testDeck.next).first().waitFor(); // an introduction first, or straight to the cards
  if (await start.count()) await start.first().click();
  await testDeck.next.waitFor();
  for (let cards = 0; cards < 40; cards++) {
    await page.waitForTimeout(450);
    const radios = page.getByRole("radiogroup", { name: "Answers" }).getByRole("radio");
    if (await radios.count()) await radios.first().click();
    else await page.getByRole("textbox").first().fill("42");
    const label = await testDeck.next.innerText();
    await testDeck.next.click();
    if (/submit/i.test(label)) break;
  }
  const confirm = page.getByRole("dialog");
  if (await confirm.count()) await confirm.getByRole("button").last().click();
  await api.until(lessonId, (lesson) => lesson.test_status === "graded");
  await page.goto(`/lessons/${lessonId}?tab=test`);
  await expect(page.getByText(/final/i).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /retake|try the test again|answer again/i })).toHaveCount(0);

  // The API says no a second time, and never sends the answers with the questions.
  const again = await api.call("POST", `/lessons/${lessonId}/test/submissions`, { answers: {} });
  expect(again.status).toBe(409);
  expect(again.body.code).toBe("already_submitted");
  const questions = await api.call("GET", `/lessons/${lessonId}/test`);
  expect(JSON.stringify(questions.body.questions)).not.toMatch(/correct_index|answer_key|marking|solution/);
});
