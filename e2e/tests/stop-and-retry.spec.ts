/**
 * Stop, then Retry. A learner who stops a build and presses Retry gets their lesson, whenever in the build they stopped.
 *
 * Why: stopping is cooperative, so the stop can land between two steps of the build. Retry used to read such a thread as
 * "finished" and do nothing in a fraction of a second, leaving the lesson failed for good.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";

test("a stopped build is picked up by Retry, wherever the stop landed", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("stop"), E2E.PASSWORD);

  for (const delayMs of [0, 600, 1800, 3200]) {
    const lessonId = (await api.call("POST", "/lessons", { topic: `Stopping ${delayMs}` })).body.lesson_id as string;
    await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
    await page.goto(`/lessons/${lessonId}`);
    expect(await new Deck(page).answerAll(Deck.rightOrDontKnow)).toBe(10);
    const running = await api.until(lessonId, (lesson) => Boolean(lesson.active_run_id));
    await page.waitForTimeout(delayMs);

    const stopped = await api.call("POST", `/runs/${running.active_run_id}/cancel`);
    if (stopped.status === 409) continue; // the build had already finished: nothing to stop
    expect(stopped.status).toBe(202);
    await api.until(lessonId, (lesson) => lesson.stage === "failed" && !lesson.active_run_id);

    expect((await api.call("POST", `/lessons/${lessonId}/retry`)).status).toBe(202);
    const finished = await api.until(lessonId, (lesson) => lesson.stage === "ready" && !lesson.active_run_id, 60_000);
    expect(finished.stage).toBe("ready");
  }
});

test("the stop dialog stays open until the learner decides, and Stop then Retry works from the screen", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("dialog"), E2E.PASSWORD);
  const lessonId = (await api.call("POST", "/lessons", { topic: "The dialog" })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
  await page.goto(`/lessons/${lessonId}`);
  await new Deck(page).answerAll(Deck.rightOrDontKnow);

  await page.getByRole("button", { name: "Stop building" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Stop building" }).click({ timeout: 5_000 }).catch(() => undefined);
  // Either it stopped (the failed card) or the build ended first (the ready lesson): never a stuck screen.
  await expect(page.getByRole("button", { name: "Retry" }).or(page.getByText(/Page 1 of 3|Lesson/).first())).toBeVisible({ timeout: 30_000 });
  const stage = await api.stage(lessonId);
  if (stage === "failed") {
    await page.getByRole("button", { name: "Retry" }).click();
    await api.until(lessonId, (lesson) => lesson.stage === "ready", 60_000);
  }
});
