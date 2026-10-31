/**
 * Follow-up lessons, in a browser against the fake model.
 *
 * - a learner who fails the test is offered a Foundation lesson in a pop-up, makes it, and is taken to it; it is a lesson
 *   of its own (Beginner, "Foundations of …") that says where it came from, and the parent links to it; failing again
 *   offers to open that lesson instead of making a second one; two requests at once make one lesson
 * - a learner who scores over 90% is offered an Advanced lesson, makes it, and is taken to an Expert lesson
 * - a learner who rated themselves a beginner and fails is told nothing in a pop-up, only given a quiet note, and no
 *   lesson is made
 *
 * Why: the policy and the service are unit-tested with the spec's six worked examples; what only the browser shows is the
 * pop-up appearing once on the result that earned it, the button taking the learner to the new lesson, a second failure
 * pointing at the lesson that exists, and a low rater never being told to start somewhere else.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { AttemptPage } from "../support/attempt";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";

/** A learner with a ready lesson from the quick check (a middling score, so they count as neither a low nor a high rater). */
async function midLesson(page: import("@playwright/test").Page, api: Api, topic: string): Promise<string> {
  const lessonId = (await api.call("POST", "/lessons", { topic })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
  await page.goto(`/lessons/${lessonId}`);
  expect(await new Deck(page).answerAll(Deck.rightOrDontKnow)).toBe(10);
  await api.until(lessonId, (lesson) => lesson.stage === "ready" && !lesson.active_run_id, 180_000);
  return lessonId;
}

async function takeTest(page: import("@playwright/test").Page, lessonId: string, mode: "right" | "wrong", again = false) {
  await page.goto(`/lessons/${lessonId}?tab=test`);
  await page.getByRole("button", { name: again ? /try again/i : /start the test/i }).click();
  expect(await new AttemptPage(page).answerAll(mode)).toBe(10);
}

test("failing the test offers a Foundation lesson once, a second failure offers to open it, and a double click makes one", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("foundation"), E2E.PASSWORD);
  const parentId = await midLesson(page, api, "Photosynthesis");

  // The first failure: a pop-up with the one thing to do, and it can be turned down.
  await takeTest(page, parentId, "wrong");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Want to build up the basics?")).toBeVisible({ timeout: 30_000 });
  await expect(dialog.getByText(/you (were|are) (wrong|a beginner)/i)).toHaveCount(0);
  await dialog.getByRole("button", { name: "Not now" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Make a Foundation lesson" })).toBeVisible(); // still there, quietly

  // Make it: the learner is taken to a lesson of its own.
  await page.getByRole("button", { name: "Make a Foundation lesson" }).click();
  await page.waitForURL((url) => /\/lessons\/[0-9a-f-]{36}$/.test(url.pathname) && !url.pathname.includes(parentId));
  const childId = page.url().split("/").pop() as string;
  const child = await api.until(childId, (lesson) => lesson.stage === "ready" && !lesson.active_run_id, 180_000);
  expect(child).toMatchObject({
    topic: "Foundations of Photosynthesis", entry: "followup", origin: "followup", followup_level: "foundation",
    level: "beginner", level_source: "test_score", route: "lesson",
  });
  expect(child.followup_of).toMatchObject({ id: parentId, level: "foundation" });
  expect(child.prerequisites_to_cover).toHaveLength(3); // a Beginner who took no quick check has them planned
  expect(child.results).toEqual({ diagnostic: null, prerequisite: null });

  // It says where it came from, and the parent links to it.
  await page.goto(`/lessons/${childId}`);
  await expect(page.getByRole("list", { name: "Related lessons" }).getByText("Made from:")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("list", { name: "Related lessons" }).getByRole("link", { name: "Photosynthesis" }).click();
  await page.waitForURL(new RegExp(`/lessons/${parentId}`));
  await expect(page.getByRole("list", { name: "Related lessons" }).getByText("Foundation lesson:")).toBeVisible({ timeout: 30_000 });

  // The second failure: the lesson that exists is offered, not another.
  await takeTest(page, parentId, "wrong", true);
  await expect(dialog.getByText("Your Foundation lesson is ready")).toBeVisible({ timeout: 30_000 });
  await dialog.getByRole("button", { name: "Open it" }).click();
  await page.waitForURL(new RegExp(`/lessons/${childId}`));

  // Two requests at the same moment for the other level make one lesson, and the loser is told which.
  const both = await Promise.all([1, 2].map(() => api.call("POST", `/lessons/${parentId}/followups`, { level: "advanced" })));
  expect(both.map((r) => r.status).sort()).toEqual([202, 409]);
  expect(both[0].body.lesson_id).toBe(both[1].body.lesson_id);
  const parent = (await api.call("GET", `/lessons/${parentId}`)).body;
  expect(parent.followups.foundation.id).toBe(childId);
  expect(parent.followups.advanced.id).toBe(both[0].body.lesson_id);
});

test("an excellent result offers an Advanced lesson, which is an Expert lesson of its own", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("advanced"), E2E.PASSWORD);
  const parentId = await midLesson(page, api, "Newton's laws");

  await takeTest(page, parentId, "right");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Ready for more?")).toBeVisible({ timeout: 30_000 });
  await dialog.getByRole("button", { name: "Make an Advanced lesson" }).click();
  await page.waitForURL((url) => /\/lessons\/[0-9a-f-]{36}$/.test(url.pathname) && !url.pathname.includes(parentId));
  const childId = page.url().split("/").pop() as string;

  const child = await api.until(childId, (lesson) => lesson.stage === "ready" && !lesson.active_run_id, 180_000);
  expect(child).toMatchObject({ topic: "Advanced Newton's laws", followup_level: "advanced", level: "expert", level_source: "test_score" });
  expect(child.prerequisites_to_cover).toEqual([]);
  expect(child.followup_of).toMatchObject({ id: parentId, level: "advanced" });
});

test("a learner who rated themselves a beginner and fails sees only a quiet note, and no lesson is made", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("low"), E2E.PASSWORD);
  const lessonId = (await api.call("POST", "/lessons", { topic: "Binary search", entry: "self_rating", self_rating: 1 })).body.lesson_id as string;
  await api.until(lessonId, (lesson) => lesson.stage === "ready" && !lesson.active_run_id, 180_000);

  await takeTest(page, lessonId, "wrong");

  await expect(page.getByText("Question by question")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("That one was a stretch")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0); // nothing pops up
  await expect(page.getByRole("button", { name: /Make a Foundation lesson|Make an Advanced lesson|Open it/ })).toHaveCount(0);
  const attempts = (await api.call("GET", `/lessons/${lessonId}/test/attempts`)).body.attempts;
  const attempt = (await api.call("GET", `/lessons/${lessonId}/test/attempts/${attempts[0].id}`)).body;
  expect(attempt.followup).toMatchObject({ kind: "inline_suggestion", action: "revisit_or_related", lesson_id: null });
  const detail = (await api.call("GET", `/lessons/${lessonId}`)).body;
  expect(detail.followups).toEqual({ foundation: null, advanced: null });
});
