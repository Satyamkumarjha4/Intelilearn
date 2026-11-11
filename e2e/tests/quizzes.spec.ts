/**
 * Quick quizzes, in a browser against the fake model.
 *
 * - a quiz on a topic found by the five-question warm-up: the learner answers the warm-up, the quiz is written at the level
 *   it found, they take it, and taking it again gives different questions and a history of the two tries
 * - a quiz from two lessons, its level set by their test scores: each lesson keeps its own level and share
 * - a five-question quiz cannot ask for short or written answers (the choice is not there), and ten questions can
 * - a quiz on a topic can become a lesson, whose level comes from the result
 * - a quiz from a lesson, answered wrong: each weak concept's "Study this" link opens the page of the lesson that teaches
 *   it (the Introduction for one concept, the Core page for another), because the questions named the lesson's own
 *   concepts and the lesson's index knows which page each is on
 *
 * Why: the services, graph and API are unit-tested; the seams only the stack shows are the wizard's rules (what it hides),
 * the warm-up one question at a time, the quiz page following the run, the shared question deck serving a quiz, a retake
 * that really has new questions, and the button that turns a result into a lesson.
 */
import { expect, test, type Page } from "@playwright/test";

import { Api } from "../support/api";
import { AttemptPage } from "../support/attempt";
import { Choose } from "../support/choose";
import { E2E } from "../support/config";

const READY = (lesson: any) => lesson.stage === "ready" && !lesson.active_run_id;

/** Polls the quiz until `done`, with what it last saw if the time runs out. */
async function untilQuiz(api: Api, _page: Page, id: string, done: (quiz: any) => boolean, ms = 180_000): Promise<any> {
  return Api.poll(() => api.call("GET", `/quick-quizzes/${id}`).then((reply) => reply.body), done, ms, "the quiz");
}

async function next(page: Page) {
  await page.getByRole("button", { name: "Next", exact: true }).click();
}

/** The wizard, from the first step to the button that makes the quiz. */
async function makeTopicQuiz(page: Page, topic: string, level: string) {
  await page.goto("/quizzes/new");
  await page.getByText("A topic", { exact: true }).click();
  await page.locator("#quiz-topic").fill(topic);
  await next(page);
  await next(page); // ten questions
  await next(page); // multiple choice
  await page.getByRole("radio", { name: level }).check({ force: true });
}

test("a topic quiz found by the warm-up, taken, then taken again with new questions", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("quiz-warmup"), E2E.PASSWORD);

  await makeTopicQuiz(page, "Binary search", "A quick warm-up");
  await page.getByRole("button", { name: "Make my quiz" }).click();
  await page.waitForURL(/\/quizzes\/[0-9a-f-]{36}$/);
  const quizId = page.url().split("/").pop() as string;

  // The warm-up: five questions, one at a time, each answer final. The fake model writes the right option as "The true statement".
  await expect(page.getByRole("heading", { name: "Question 1 of 5" })).toBeVisible({ timeout: 120_000 });
  for (let step = 1; step <= 5; step++) {
    await expect(page.getByRole("heading", { name: `Question ${step} of 5` })).toBeVisible();
    await Choose.option(page.getByRole("radiogroup", { name: "Answers" }).getByRole("radio", { name: /true statement/ }));
    // `next dev` starts the warm-up twice (React's strict mode), and an answer sent in the moment between is ignored: the
    // button then stays as it was. So press it again until the next question is there (production starts it once).
    await expect(async () => {
      await page.getByRole("button", { name: step === 5 ? "Finish" : "Continue" }).click({ timeout: 2_000 });
      if (step < 5) await expect(page.getByRole("heading", { name: `Question ${step + 1} of 5` })).toBeVisible({ timeout: 5_000 });
    }).toPass({ timeout: 60_000 });
  }

  // Five right answers is an Expert; the quiz is written for that level and waits to be taken.
  const ready = await untilQuiz(api, page, quizId, (quiz) => quiz.stage === "ready" && quiz.open_attempt?.status === "in_progress");
  expect(ready).toMatchObject({ level: "expert", level_source: "calibration", source_type: "topic" });
  expect(ready.config).toMatchObject({ num_questions: 10, types: ["mcq"], level_mode: "calibration" });

  await page.goto(`/quizzes/${quizId}`);
  expect(await new AttemptPage(page).answerAll("right")).toBe(10);
  await expect(page.getByText("Try again with new questions")).toBeVisible({ timeout: 60_000 });
  const first = await api.call("GET", `/quick-quizzes/${quizId}/attempts/${ready.open_attempt.id}`);
  expect(first.body).toMatchObject({ status: "graded", band: "excellent", awarded: first.body.available });

  // A retake is a new set: nothing the quiz asked before comes back.
  await page.getByRole("button", { name: "Try again with new questions" }).click();
  const retaking = await untilQuiz(api, page, quizId, (quiz) => quiz.open_attempt?.attempt_no === 2 && quiz.open_attempt.status === "in_progress");
  const second = await api.call("GET", `/quick-quizzes/${quizId}/attempts/${retaking.open_attempt.id}`);
  const asked = new Set(first.body.questions.map((q: any) => q.question));
  expect(second.body.questions).toHaveLength(10);
  expect(second.body.questions.filter((q: any) => asked.has(q.question))).toEqual([]);

  await page.goto(`/quizzes/${quizId}`);
  expect(await new AttemptPage(page).answerAll("wrong")).toBe(10);
  await expect(page.getByRole("heading", { name: "Your tries" })).toBeVisible({ timeout: 60_000 }); // two tries to compare
  const history = (await api.call("GET", `/quick-quizzes/${quizId}/attempts`)).body;
  expect(history.attempts.map((a: any) => [a.attempt_no, a.status])).toEqual([[1, "graded"], [2, "graded"]]);
  expect(history.trend.series[1].delta_previous).toBeLessThan(0);
});

test("a quiz from two lessons uses their test scores: each lesson keeps its own level and share", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("quiz-lessons"), E2E.PASSWORD);
  // Two lessons by rating (no quick check), each with a test taken and failed: a score moves a level one step down.
  const proficient = (await api.call("POST", "/lessons", { topic: "Fractions", entry: "self_rating", self_rating: 4 })).body.lesson_id as string;
  const foundation = (await api.call("POST", "/lessons", { topic: "Decimals", entry: "self_rating", self_rating: 2 })).body.lesson_id as string;
  for (const id of [proficient, foundation]) {
    await api.until(id, READY, 180_000);
    const started = (await api.call("POST", `/lessons/${id}/test/attempts`)).body;
    expect((await api.call("POST", `/lessons/${id}/test/attempts/${started.attempt_id}/submit`, {})).status).toBe(200);
  }

  await page.goto("/quizzes/new");
  await page.getByText("My lessons", { exact: true }).click();
  await expect(page.getByText("Pick up to 10 lessons · 0 picked")).toBeVisible();
  await page.getByRole("checkbox", { name: /Fractions/ }).check();
  await page.getByRole("checkbox", { name: /Decimals/ }).check();
  await next(page);
  await next(page); // ten questions
  await next(page); // multiple choice
  await expect(page.getByRole("radio", { name: /Use my test scores/ })).toBeChecked(); // both have a score, so it starts there
  await page.getByRole("button", { name: "Make my quiz" }).click();
  await page.waitForURL(/\/quizzes\/[0-9a-f-]{36}$/);
  const quizId = page.url().split("/").pop() as string;

  const quiz = await untilQuiz(api, page, quizId, (q) => q.stage === "ready" && q.open_attempt?.status === "in_progress");
  expect(quiz.source_type).toBe("lessons");
  expect(quiz.sources.map((s: any) => [s.title, s.level, s.share])).toEqual([["Fractions", "foundation", 5], ["Decimals", "beginner", 5]]);
  expect(quiz.config.level_mode).toBe("existing_score");
  const attempt = (await api.call("GET", `/quick-quizzes/${quizId}/attempts/${quiz.open_attempt.id}`)).body;
  expect(attempt.questions).toHaveLength(10);
  expect(JSON.stringify(attempt)).not.toContain("source"); // which lesson a question is about is not shown while it is open
});

test("a five-question quiz cannot ask for short or written answers; ten can", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("quiz-types"), E2E.PASSWORD);

  await page.goto("/quizzes/new");
  await page.getByText("A topic", { exact: true }).click();
  await page.locator("#quiz-topic").fill("Solving equations");
  await next(page);
  await page.getByRole("button", { name: "5", exact: true }).click();
  await next(page);
  await expect(page.getByText("Multiple choice", { exact: true })).toBeVisible();
  await expect(page.getByText("Short answers", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Written answers", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Short and written answers need 10 or more questions.")).toBeVisible();

  await page.getByRole("button", { name: "Back" }).click();
  await page.getByRole("button", { name: "10", exact: true }).click();
  await next(page);
  await expect(page.getByText("Short answers", { exact: true })).toBeVisible();
  await expect(page.getByText("Written answers", { exact: true })).toBeVisible();
  // The server's refusal of the same by hand is proved by tests/quizzes/test_views.py and tests/graph/test_quiz_config.py.
});

test("a quiz on a topic becomes a lesson whose level comes from the result", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("quiz-lesson"), E2E.PASSWORD);
  const made = await api.call("POST", "/quick-quizzes", {
    source: { type: "topic", topic: "Photosynthesis" }, num_questions: 5, types: ["mcq"], level: { mode: "self_rating", rating: 4 },
  });
  expect(made.status).toBe(202);
  const quizId = made.body.quiz_id as string;
  const quiz = await untilQuiz(api, page, quizId, (q) => q.stage === "ready" && q.open_attempt?.status === "in_progress");
  expect(quiz.level).toBe("proficient");

  await page.goto(`/quizzes/${quizId}`);
  expect(await new AttemptPage(page).answerAll("wrong")).toBe(5);
  await page.getByRole("button", { name: "Create a lesson for this" }).click();
  await page.waitForURL(/\/lessons\/[0-9a-f-]{36}$/);
  const lessonId = page.url().split("/").pop() as string;

  const lesson = await api.until(lessonId, READY, 180_000);
  expect(lesson).toMatchObject({ topic: "Photosynthesis", entry: "quiz_result", origin: "quiz_result", level_source: "quiz_result", route: "lesson" });
  expect(lesson.level).toBe("foundation"); // proficient, moved one down by a failed quiz
});

test("a quiz from a lesson sends each weak concept to the page that teaches it", async ({ page }) => {
  const api = new Api(page);
  await api.signUp(E2E.email("quiz-study"), E2E.PASSWORD);
  const lessonId = (await api.call("POST", "/lessons", { topic: "Fractions", entry: "self_rating", self_rating: 4 })).body.lesson_id as string;
  await api.until(lessonId, READY, 180_000);
  const made = await api.call("POST", "/quick-quizzes", {
    source: { type: "lessons", lesson_ids: [lessonId] }, num_questions: 5, types: ["mcq"], level: { mode: "self_rating", rating: 4 },
  });
  expect(made.status).toBe(202);
  const quizId = made.body.quiz_id as string;
  const quiz = await untilQuiz(api, page, quizId, (q) => q.stage === "ready" && q.open_attempt?.status === "in_progress");

  await page.goto(`/quizzes/${quizId}`);
  expect(await new AttemptPage(page).answerAll("wrong")).toBe(5);
  await expect(page.getByRole("heading", { name: "Worth another look" })).toBeVisible({ timeout: 60_000 });

  // The server's advice has a page for each concept, from the lesson's own index: the questions named the lesson's own
  // concepts (the fake model copies them from the prompt, as the real one is told to), so every one is found.
  const attempt = (await api.call("GET", `/quick-quizzes/${quizId}/attempts/${quiz.open_attempt.id}`)).body;
  const links = attempt.recommendations.lessons[0].links;
  expect(links.map((l: any) => [l.concept, l.page]).sort()).toEqual([
    ["A worked example of Fractions", "core"], ["The main idea of Fractions", "core"], ["The vocabulary of Fractions", "introduction"],
    ["What Fractions is", "introduction"], ["Why Fractions matters", "introduction"],
  ]);

  // Study this opens that page of the lesson, not just the lesson.
  await page.getByRole("link", { name: /Study this.*The main idea of Fractions/ }).click();
  await page.waitForURL(new RegExp(`/lessons/${lessonId}\\?tab=lesson&page=core`));
  await expect(page.getByText("Page 2 of 3 · Core")).toBeVisible({ timeout: 60_000 });

  await page.goBack();
  await page.getByRole("link", { name: /Study this.*What Fractions is/ }).click();
  await page.waitForURL(new RegExp(`/lessons/${lessonId}\\?tab=lesson&page=introduction`));
  await expect(page.getByText("Page 1 of 3 · Introduction")).toBeVisible({ timeout: 60_000 });
});
