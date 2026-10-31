/**
 * The learner's whole path, in a browser, against the fake model: the landing page's question, sign-up with consent,
 * the five-step setup, a suggested topic, a forward-only quick check, the lesson book, a test that is marked the moment
 * it is handed in, Try again with questions written for the retake, the history with its trend, and what the API
 * refuses afterwards (an attempt that is over cannot change).
 *
 * Why: each screen is unit-tested, but the seams (the cookie after sign-up, the guard's redirects, a run that builds
 * while the page polls, a retake that waits for its questions, an attempt that must not be answerable twice) only show
 * in the browser.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { AttemptPage } from "../support/attempt";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";
import { Onboarding } from "../support/onboarding";

test("a learner signs up, learns, takes the test, tries again with new questions and sees the trend", async ({ page }) => {
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

  // The test: start it, answer every card wrongly on purpose, hand it in, and the marks are there at once.
  await page.goto(`/lessons/${lessonId}?tab=test`);
  await page.getByRole("button", { name: /start the test/i }).click();
  const attempt = new AttemptPage(page);
  expect(await attempt.answerAll("wrong")).toBe(10);
  await expect(page.getByText("Question by question")).toBeVisible({ timeout: 30_000 });
  await attempt.dismissOffer(); // a failed result offers a Foundation lesson, which this journey does not want
  await expect(page.getByText(/attempt 1/i).first()).toBeVisible();
  await expect(page.getByText(/your test is final|only attempt|one attempt/i)).toHaveCount(0); // nothing says it is the last go
  await expect(page.getByRole("button", { name: /try again/i })).toBeVisible();
  const first = await api.call("GET", `/lessons/${lessonId}/test/attempts`);
  expect(first.body.attempts).toHaveLength(1);
  expect(first.body.attempts[0]).toMatchObject({ attempt_no: 1, status: "graded", band: "fail" });

  // Try again: the questions are written for the retake, and the second go is a different set.
  const started = page.waitForResponse((r) => r.url().endsWith(`/test/attempts`) && r.request().method() === "POST");
  await page.getByRole("button", { name: /try again/i }).click();
  expect((await started).status()).toBe(202); // a retake always generates
  expect(await attempt.answerAll("right")).toBe(10);
  await expect(page.getByText("Your tries")).toBeVisible({ timeout: 30_000 });
  await attempt.dismissOffer(); // and an excellent one offers an Advanced lesson
  await expect(page.getByText(/up 100 points on last time/i).first()).toBeVisible();
  await expect(page.getByText("A new best").first()).toBeVisible();
  await expect(page.getByText("100%").first()).toBeVisible();

  const history = await api.call("GET", `/lessons/${lessonId}/test/attempts`);
  expect(history.body.attempts.map((a: any) => [a.attempt_no, a.status, a.percent])).toEqual([[1, "graded", 0], [2, "graded", 100]]);
  expect(history.body.trend.best_attempt_no).toBe(2);
  const [one, two] = await Promise.all(
    history.body.attempts.map((a: any) => api.call("GET", `/lessons/${lessonId}/test/attempts/${a.id}`)),
  );
  const asked = (reply: any) => reply.body.questions.map((q: any) => q.question);
  expect(asked(one)).toHaveLength(10);
  expect(asked(two).filter((text: string) => asked(one).includes(text))).toEqual([]); // no question comes back

  // The lesson list says how the test went, whatever the last go was.
  await page.goto("/lessons");
  await expect(page.getByText(/Test done · best 100%/).first()).toBeVisible();

  // An attempt that is over cannot change, the old single call is refused, and no answer key is ever sent.
  const sealed = await api.call("PUT", `/lessons/${lessonId}/test/attempts/${two.body.id}/answers/t1`, { answer: 0 });
  expect([sealed.status, sealed.body.code]).toEqual([409, "attempt_sealed"]);
  const again = await api.call("POST", `/lessons/${lessonId}/test/attempts/${two.body.id}/submit`, {});
  expect([again.status, again.body.code]).toEqual([409, "attempt_sealed"]);
  const old = await api.call("POST", `/lessons/${lessonId}/test/submissions`, { answers: {} });
  expect([old.status, old.body.code]).toEqual([409, "already_submitted"]);
  const open = await api.call("GET", `/lessons/${lessonId}/test`);
  expect(open.body.questions).toEqual([]); // nothing is open, so nothing is served
  expect(JSON.stringify(open.body)).not.toMatch(/correct_index|correct_indices|answer_expr|tolerance|model_answer/);
});
