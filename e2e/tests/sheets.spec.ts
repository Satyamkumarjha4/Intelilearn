/**
 * Study sheets for any lesson, in a browser against the fake model.
 *
 * - a learner asks for study sheets only from a topic, by quick check: whatever they score, there is no prerequisite quiz
 *   and no choice, and the lesson ends with both sheets, no lesson pages and no test
 * - the same by rating themselves: no quiz at all, and a Beginner's prerequisites are not planned for a lesson that will
 *   never exist
 * - a ready lesson can have one sheet made, then the other; both cannot be asked for when one exists, and a request
 *   for a sheet that exists (a page that was out of date) simply opens it instead of making it again
 * - a sheets-only lesson can be asked for its missing sheet too, and cannot be followed up (it has no test)
 *
 * Why: the services, graphs and API are unit-tested; the seams only the stack shows are the new-lesson screen's second
 * question, the quick check that goes on to sheets whatever the score, the tabs of a lesson with no lesson, and the tab row
 * of any ready lesson asking for a sheet and being told it exists.
 */
import { expect, test } from "@playwright/test";

import { Api } from "../support/api";
import { E2E } from "../support/config";
import { Deck } from "../support/deck";

const READY = (lesson: any) => lesson.stage === "ready" && !lesson.active_run_id;

test("study sheets from a topic by quick check: any score, both sheets, no lesson and no test", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("sheets-quiz"), E2E.PASSWORD);

  await page.goto("/lessons/new");
  await page.getByLabel("Topic").fill("Newton's laws");
  await page.getByText("Study sheets", { exact: true }).click();
  await expect(page.getByRole("radio", { name: /Both/ })).toBeChecked(); // both is picked at first
  await page.getByRole("button", { name: "Start my quick check" }).click();
  await page.waitForURL(/\/lessons\/[0-9a-f-]{36}$/);
  const lessonId = page.url().split("/").pop() as string;

  await api.until(lessonId, (lesson) => lesson.stage === "awaiting_diagnostic");
  await page.goto(`/lessons/${lessonId}`);
  expect(await new Deck(page).answerAll(Deck.rightOrDontKnow)).toBe(10); // a middling score: a lesson would plan prerequisites

  const lesson = await api.until(lessonId, READY, 180_000);
  expect(lesson).toMatchObject({ intent: "sheets", sheets_only: true, route: "", entry: "diagnostic", materials: ["cheat_sheet", "revision_sheet"] });
  expect(lesson.prerequisites_to_cover).toEqual([]);
  expect((await api.call("GET", `/lessons/${lessonId}/test`)).status).toBe(409); // there is no test

  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByRole("tab", { name: "Study sheets" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("tab", { name: "Test" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Lesson" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cheat sheet", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Revision sheet", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Add / })).toHaveCount(0); // both exist: nothing left to add
});

test("study sheets from a topic by rating yourself: no quiz, both sheets", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("sheets-rated"), E2E.PASSWORD);

  await page.goto("/lessons/new");
  await page.getByLabel("Topic").fill("Photosynthesis");
  await page.getByText("Study sheets", { exact: true }).click();
  await page.getByText("Rate yourself", { exact: true }).click();
  await expect(page.getByRole("button", { name: "Make my two sheets" })).toBeDisabled(); // a rating is needed first
  const first = page.getByRole("radio", { name: "0.5 stars", exact: true });
  await first.focus();
  await page.keyboard.press("ArrowRight"); // nothing was picked, so the first arrow picks the first value
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "1 star", exact: true })).toBeChecked(); // a Beginner
  await page.getByRole("button", { name: "Make my two sheets" }).click();
  await page.waitForURL(/\/lessons\/[0-9a-f-]{36}$/);
  const lessonId = page.url().split("/").pop() as string;

  const lesson = await api.until(lessonId, READY, 180_000);
  expect(lesson).toMatchObject({
    intent: "sheets", sheets_only: true, entry: "self_rating", level: "beginner", level_source: "self_rating",
    route: "", materials: ["cheat_sheet", "revision_sheet"], results: { diagnostic: null, prerequisite: null },
  });
  expect(lesson.prerequisites_to_cover).toEqual([]); // nothing is planned for a lesson that will never exist

  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByRole("tab", { name: "Study sheets" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("tab", { name: "Quick check answers" })).toHaveCount(0);
  await expect(page.getByText("Rate yourself").first()).toBeVisible(); // the journey's first step
});

test("a ready lesson gets one sheet, then the other; a request for one that exists opens it", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("sheets-extra"), E2E.PASSWORD);
  const lessonId = (await api.call("POST", "/lessons", { topic: "Binary search", entry: "self_rating", self_rating: 4 })).body.lesson_id as string;
  await api.until(lessonId, READY, 180_000);

  await page.goto(`/lessons/${lessonId}?tab=sheets`);
  await expect(page.getByRole("button", { name: "Add both sheets" })).toBeVisible(); // neither exists yet
  await page.getByRole("button", { name: "Add cheat sheet" }).click();
  await expect(page.getByRole("button", { name: "Cheat sheet", exact: true })).toBeVisible({ timeout: 120_000 });
  await api.until(lessonId, (l) => READY(l) && l.materials.length === 1, 120_000);
  await expect(page.getByRole("button", { name: "Add both sheets" })).toHaveCount(0); // one exists now
  const cheat = await api.call("GET", `/lessons/${lessonId}/materials/cheat_sheet`);
  expect(cheat.status).toBe(200);

  await page.getByRole("button", { name: "Add revision sheet" }).click();
  await expect(page.getByRole("button", { name: "Revision sheet", exact: true })).toBeVisible({ timeout: 120_000 });
  const done = await api.until(lessonId, (l) => READY(l) && l.materials.length === 2, 120_000);
  expect(done.stage).toBe("ready"); // the lesson was ready throughout
  expect((await api.call("GET", `/lessons/${lessonId}/materials`)).body.map((m: any) => m.kind)).toEqual(["cheat_sheet", "revision_sheet"]);

  // A second request is a 409 that names what exists, and makes nothing.
  const again = await api.call("POST", `/lessons/${lessonId}/materials`, { kinds: ["cheat_sheet", "revision_sheet"] });
  expect(again.status).toBe(409);
  expect(again.body).toMatchObject({ code: "already_exists", kinds: ["cheat_sheet", "revision_sheet"] });
  expect((await api.call("GET", `/lessons/${lessonId}`)).body.active_run_id).toBeNull();
});

test("a page that was out of date opens the sheet that exists instead of making another", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("sheets-stale"), E2E.PASSWORD);
  const lessonId = (await api.call("POST", "/lessons", { topic: "Fractions", entry: "self_rating", self_rating: 4 })).body.lesson_id as string;
  await api.until(lessonId, READY, 180_000);

  await page.goto(`/lessons/${lessonId}?tab=sheets`);
  await expect(page.getByRole("button", { name: "Add cheat sheet" })).toBeVisible();
  // Meanwhile (another tab, say) the sheet is made.
  expect((await api.call("POST", `/lessons/${lessonId}/materials`, { kind: "cheat_sheet" })).status).toBe(202);
  await api.until(lessonId, (l) => READY(l) && l.materials.includes("cheat_sheet"), 120_000);

  await page.getByRole("button", { name: "Add cheat sheet" }).click(); // the page still thinks it is missing
  await expect(page.getByRole("button", { name: "Cheat sheet", exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Add cheat sheet" })).toHaveCount(0);
  expect((await api.call("GET", `/lessons/${lessonId}/materials`)).body).toHaveLength(1); // nothing was made twice
});

test("a lesson of sheets only can be asked for the sheet it lacks, and has no follow-ups", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("sheets-only"), E2E.PASSWORD);
  const created = await api.call("POST", "/lessons", {
    topic: "Newton's laws", intent: "sheets", sheets: ["cheat_sheet"], entry: "self_rating", self_rating: 4,
  });
  expect(created.status).toBe(202);
  const lessonId = created.body.lesson_id as string;
  const lesson = await api.until(lessonId, READY, 180_000);
  expect(lesson).toMatchObject({ sheets_only: true, materials: ["cheat_sheet"], sheets_asked: ["cheat_sheet"] });

  const followup = await api.call("POST", `/lessons/${lessonId}/followups`, { level: "foundation" });
  expect([followup.status, followup.body.code]).toEqual([400, "sheets_only"]);

  await page.goto(`/lessons/${lessonId}`);
  await expect(page.getByRole("button", { name: "Add cheat sheet" })).toHaveCount(0);
  await page.getByRole("button", { name: "Add revision sheet" }).click();
  await expect(page.getByRole("button", { name: "Revision sheet", exact: true })).toBeVisible({ timeout: 120_000 });
  await api.until(lessonId, (l) => READY(l) && l.materials.length === 2, 120_000);
});
