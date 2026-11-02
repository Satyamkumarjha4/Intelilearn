/**
 * Rating yourself, and the choice after a perfect quick check, in a browser against the fake model.
 *
 * - a learner rates themselves with the keyboard on the new-lesson screen and gets a lesson with no quiz: a Beginner has
 *   their prerequisites planned (and the lesson says so), an Expert has none; the journey says "Rate yourself" and there
 *   are no quick check answers to look back at; the API tells how the level was found and the rating
 * - a self-rated build that is stopped is picked up by Retry
 * - a perfect quick check shows exactly two options, and each reaches a ready lesson: the Expert lesson (with a test, its
 *   level set to Expert) or two sheets (no test)
 * - the API refuses an origin only the server may set, and a recommendation that is not the learner's own
 *
 * Why: the unit tests cover each piece; the seams (the star rating's keyboard, a lesson that starts with no quiz and
 * still plans a Beginner's prerequisites, two sheets written in parallel, a choice that sets the route the test needs)
 * only show with the real stack.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { AttemptPage } from "../support/attempt";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";

test("a learner rates themselves with the keyboard and gets a Beginner lesson with no quiz", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("rated"), E2E.PASSWORD);

  await page.goto("/lessons/new");
  await page.getByLabel("Topic").fill("Photosynthesis");
  await page.getByText("Rate yourself", { exact: true }).click();
  await expect(page.getByRole("button", { name: "Start my lesson" })).toBeDisabled(); // a rating is needed

  const first = page.getByRole("radio", { name: "0.5 stars", exact: true });
  await first.focus();
  await page.keyboard.press("ArrowRight"); // nothing was picked, so the first arrow picks the first value
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "1 star", exact: true })).toBeChecked();
  await expect(page.getByText("I've heard the name, but I don't know what it means.")).toBeVisible();
  await page.keyboard.press("End");
  await expect(page.getByRole("radio", { name: "5 stars", exact: true })).toBeChecked();
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowRight"); // 1 star: a Beginner
  await expect(page.getByRole("radio", { name: "1 star", exact: true })).toBeChecked();

  await page.getByRole("button", { name: "Start my lesson" }).click();
  await page.waitForURL(/\/lessons\/[0-9a-f-]{36}$/);
  const lessonId = page.url().split("/").pop() as string;

  const lesson = await api.until(lessonId, (l) => l.stage === "ready" && !l.active_run_id, 180_000);
  expect(lesson).toMatchObject({ entry: "self_rating", self_rating: 1, level: "beginner", level_source: "self_rating", route: "lesson" });
  expect(lesson.assessment).toMatchObject({ source: "self_rating", level: "beginner" });
  expect(lesson.prerequisites_to_cover).toHaveLength(3); // nobody tested them, so they were planned
  expect(lesson.results).toEqual({ diagnostic: null, prerequisite: null }); // and there was no quiz

  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByText(/Page 1 of 3/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Rate yourself").first()).toBeVisible(); // the journey's first step
  await expect(page.getByText("Diagnose")).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Test" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Quick check answers" })).toHaveCount(0); // there was no quick check
});

test("an Expert who rates themselves gets a lesson with no prerequisites, a test and the same reading", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("expert"), E2E.PASSWORD);

  const created = await api.call("POST", "/lessons", { topic: "Binary search", entry: "self_rating", self_rating: 5 });
  expect(created.status).toBe(202);
  const lessonId = created.body.lesson_id as string;

  const lesson = await api.until(lessonId, (l) => l.stage === "ready" && !l.active_run_id, 180_000);
  expect(lesson).toMatchObject({ entry: "self_rating", self_rating: 5, level: "expert", level_source: "self_rating", route: "lesson" });
  expect(lesson.prerequisites_to_cover).toEqual([]);

  await page.goto(`/lessons/${lessonId}?tab=test`);
  await page.getByRole("button", { name: /start the test/i }).click();
  expect(await new AttemptPage(page).answerAll("right")).toBe(10); // the test works like any other
  await expect(page.getByText("100%").first()).toBeVisible({ timeout: 30_000 });
});

test("what the API refuses when a lesson is asked for", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("refused"), E2E.PASSWORD);
  const ask = (body: object) => api.call("POST", "/lessons", { topic: "Binary search", ...body });

  expect((await ask({ entry: "self_rating" })).body.fields).toHaveProperty("self_rating"); // no rating
  expect((await ask({ entry: "self_rating", self_rating: 2.3 })).status).toBe(400); // not a half step
  expect((await ask({ self_rating: 3 })).status).toBe(400); // a rating needs its entry
  expect((await ask({ intent: "sheets" })).body.fields).toHaveProperty("sheets"); // sheets need to be named
  expect((await ask({ intent: "sheets", sheets: ["practice_sheet"] })).body.fields).toHaveProperty("sheets"); // not offered
  expect((await ask({ sheets: ["cheat_sheet"] })).body.fields).toHaveProperty("sheets"); // sheets go with their intent
  expect((await ask({ origin: "followup" })).body.fields).toHaveProperty("origin"); // only the server may say so
  expect((await ask({ origin: "quiz_result" })).body.fields).toHaveProperty("origin");
  const made = await ask({ origin: "recommendation", recommended_from: { attempt_id: "6f3a1c1e-1111-4222-8333-444455556666", topic: "Anything" } });
  expect([made.status, Object.keys(made.body.fields)]).toEqual([400, ["recommended_from"]]); // not one of their attempts
});

test("a self-rated build that is stopped is picked up by Retry, wherever the stop landed", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("rated-stop"), E2E.PASSWORD);

  for (const [delayMs, stars] of [[0, 1], [800, 1], [2500, 5]] as const) {
    const lessonId = (await api.call("POST", "/lessons", { topic: `Stopping ${delayMs}`, entry: "self_rating", self_rating: stars })).body
      .lesson_id as string;
    const running = await api.until(lessonId, (lesson) => Boolean(lesson.active_run_id));
    await page.waitForTimeout(delayMs);

    const stopped = await api.call("POST", `/runs/${running.active_run_id}/cancel`);
    if (stopped.status === 409) continue; // the build had already finished
    expect(stopped.status).toBe(202);
    await api.until(lessonId, (lesson) => lesson.stage === "failed" && !lesson.active_run_id);

    expect((await api.call("POST", `/lessons/${lessonId}/retry`)).status).toBe(202);
    const finished = await api.until(lessonId, (lesson) => lesson.stage === "ready" && !lesson.active_run_id, 120_000);
    expect(finished.level_source).toBe("self_rating");
  }
});

/** A lesson whose quick check was answered perfectly, waiting at the choice. */
async function perfectLesson(page: import("@playwright/test").Page, api: Api, topic: string): Promise<string> {
  const lessonId = (await api.call("POST", "/lessons", { topic })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
  await page.goto(`/lessons/${lessonId}`);
  expect(await new Deck(page).answerAll(Deck.allRight)).toBe(10);
  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_choice" && !lesson.active_run_id);
  return lessonId;
}

test("a perfect quick check offers the Expert lesson or two sheets, and the lesson option has a test", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("perfect-lesson"), E2E.PASSWORD);
  const lessonId = await perfectLesson(page, api, "Photosynthesis");

  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByRole("radio")).toHaveCount(2);
  await expect(page.getByText("Continue with an Expert lesson")).toBeVisible();
  await expect(page.getByText("Cheat sheet + revision sheet only")).toBeVisible();
  await expect(page.getByRole("radio", { name: /Continue with an Expert lesson/ })).toBeChecked(); // the lesson is the default
  const detail = (await api.call("GET", `/lessons/${lessonId}`)).body;
  expect(detail).toMatchObject({ route: "mastery" });
  expect(detail).not.toHaveProperty("mastery_options"); // there is one version of the choice

  await page.getByRole("button", { name: "Start my Expert lesson" }).click();
  const lesson = await api.until(lessonId, (l) => l.stage === "ready" && !l.active_run_id, 180_000);
  expect(lesson).toMatchObject({ route: "lesson", level: "expert", level_source: "diagnostic", materials: [] });

  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByText(/Page 1 of 3/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("tab", { name: "Test" })).toBeVisible();
  await page.goto(`/lessons/${lessonId}?tab=test`);
  await expect(page.getByRole("button", { name: /start the test/i })).toBeVisible();
});

test("a perfect quick check can take just the two sheets, which have no test", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("perfect-sheets"), E2E.PASSWORD);
  const lessonId = await perfectLesson(page, api, "Newton's laws");

  await page.goto(`/lessons/${lessonId}`);
  await page.getByText("Cheat sheet + revision sheet only").click();
  await page.getByRole("button", { name: "Make my two sheets" }).click();

  const lesson = await api.until(lessonId, (l) => l.stage === "ready" && !l.active_run_id, 180_000);
  expect(lesson).toMatchObject({ route: "mastery", materials: ["cheat_sheet", "revision_sheet"] });

  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByRole("tab", { name: "Study sheets" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("tab", { name: "Test" })).toHaveCount(0); // sheets only, no test
  const test_ = await api.call("GET", `/lessons/${lessonId}/test`);
  expect(test_.status).toBe(409); // a mastery lesson has no test
});
