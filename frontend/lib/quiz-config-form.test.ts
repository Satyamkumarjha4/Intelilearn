/**
 * Unit under test: `QuizConfigForm`, the rules of the "New quick quiz" wizard (source, how many, kinds of question,
 * level).
 *
 * Why: the server refuses a count that is not a preset, more than ten lessons, a count below the number of lessons and a
 * written answer in a short quiz. The wizard has to keep the learner from asking for any of them (the choices are hidden,
 * not refused afterwards), keep the pieces consistent when one changes (more lessons raise the count, a smaller count
 * drops the written kinds), and send exactly the request the API takes.
 *
 * Use cases:
 * - lists as sources only lessons that are ready and have pages, newest first, and says which have a graded test
 * - shows the presets 5 to 30, and hides those below the number of lessons picked
 * - picks and drops lessons, up to ten and no more, and raises the count when the lessons outgrow it
 * - drops the written kinds when the count goes below ten, and the numbers when the topic is not about calculation
 * - starts the level on the learner's scores when every lesson has one and on their rating otherwise, and uses their
 *   own pick when they made one, whatever the lessons say
 * - a step is ready when its part is valid: a topic of two letters, a lesson picked, a count on offer, a kind, a level
 *   that can be used and is complete
 * - builds the request for a topic and for lessons, with the rating in stars, and nothing while the form is incomplete
 */
import { describe, expect, test } from "bun:test";

import { QuizConfigForm, type EligibleLesson, type QuizFormState } from "./quiz-config-form";
import type { LessonSummary } from "./types";

const lesson = (id: string, fields: Partial<LessonSummary> = {}): LessonSummary =>
  ({
    id, topic: `Topic ${id}`, title: `Title ${id}`, stage: "ready", intent: "lesson", sheets_only: false, level: "foundation",
    latest_score: { awarded: 8, available: 10 }, created_at: `2026-01-0${id}T00:00:00Z`, ...fields,
  }) as unknown as LessonSummary;

const eligible = (n: number, scored = true): EligibleLesson[] =>
  Array.from({ length: n }, (_, i) => ({ id: String(i + 1), title: `L${i + 1}`, level: "foundation", scored, created: `2026-01-0${i + 1}` }));

const withLessons = (ids: string[], more: Partial<QuizFormState> = {}): QuizFormState => ({
  ...QuizConfigForm.initial(), source: "lessons", lessonIds: ids, ...more,
});

describe("the lessons on offer", () => {
  test("only ready lessons with pages, newest first, with whether they have a score", () => {
    const lessons = [
      lesson("1"),
      lesson("2", { stage: "generating_lesson" }),
      lesson("3", { intent: "sheets", sheets_only: true }),
      lesson("4", { sheets_only: true }),
      lesson("5", { latest_score: null, title: "", topic: "Sorting" }),
    ];

    expect(QuizConfigForm.eligible(lessons)).toEqual([
      { id: "5", title: "Sorting", level: "foundation", scored: false, created: "2026-01-05T00:00:00Z" },
      { id: "1", title: "Title 1", level: "foundation", scored: true, created: "2026-01-01T00:00:00Z" },
    ]);
  });
});

describe("the counts", () => {
  test("are the six presets for a topic", () => {
    expect(QuizConfigForm.counts(QuizConfigForm.initial())).toEqual([5, 10, 15, 20, 25, 30]);
  });

  test.each([
    [0, [5, 10, 15, 20, 25, 30]],
    [5, [5, 10, 15, 20, 25, 30]],
    [6, [10, 15, 20, 25, 30]],
    [10, [10, 15, 20, 25, 30]],
  ])("with %p lessons picked the counts are %p", (n, counts) => {
    const state = withLessons(Array.from({ length: n }, (_, i) => String(i + 1)));
    expect(QuizConfigForm.counts(state)).toEqual(counts);
  });

  test("a topic quiz ignores the lessons that were picked before", () => {
    expect(QuizConfigForm.counts({ source: "topic", lessonIds: ["1", "2", "3", "4", "5", "6"] })).toEqual([5, 10, 15, 20, 25, 30]);
  });

  test("a count that is not on offer becomes the smallest that is", () => {
    const state = withLessons(["1", "2", "3", "4", "5", "6"], { count: 5 });
    expect(QuizConfigForm.setCount(state, 5).count).toBe(10);
    expect(QuizConfigForm.setCount(state, 7).count).toBe(10);
    expect(QuizConfigForm.setCount(state, 20).count).toBe(20);
  });

  test("a smaller count drops the written kinds", () => {
    const state = { ...QuizConfigForm.initial(), count: 15, types: ["mcq", "long_answer"] as QuizFormState["types"] };
    expect(QuizConfigForm.setCount(state, 5).types).toEqual(["mcq"]);
    expect(QuizConfigForm.setCount(state, 10).types).toEqual(["mcq", "long_answer"]);
  });

  test("a topic that is not about calculation drops the number questions", () => {
    const state = { ...QuizConfigForm.initial(), types: ["mcq", "numerical"] as QuizFormState["types"] };
    expect(QuizConfigForm.setCount(state, 10, { numerical: false, code: false }).types).toEqual(["mcq"]);
  });
});

describe("picking lessons", () => {
  test("adds and drops a lesson in the order picked", () => {
    let state = QuizConfigForm.setSource(QuizConfigForm.initial(), "lessons");
    state = QuizConfigForm.toggleLesson(state, "2");
    state = QuizConfigForm.toggleLesson(state, "1");
    expect(state.lessonIds).toEqual(["2", "1"]);
    expect(QuizConfigForm.toggleLesson(state, "2").lessonIds).toEqual(["1"]);
  });

  test("allows ten lessons and no more", () => {
    let state = QuizConfigForm.setSource(QuizConfigForm.initial(), "lessons");
    for (let n = 1; n <= 11; n++) state = QuizConfigForm.toggleLesson(state, String(n));

    expect(state.lessonIds).toHaveLength(10);
    expect(QuizConfigForm.canAddLesson(state, "11")).toBe(false);
    expect(QuizConfigForm.canAddLesson(state, "3")).toBe(true); // one that is picked can always be dropped
  });

  test("raises the count when the lessons outgrow it", () => {
    let state = { ...QuizConfigForm.setSource(QuizConfigForm.initial(), "lessons"), count: 5 };
    for (let n = 1; n <= 6; n++) state = QuizConfigForm.toggleLesson(state, String(n));

    expect(state.count).toBe(10);
  });

  test("changing the source forgets the level that was picked for the other", () => {
    const state = QuizConfigForm.setMode({ ...QuizConfigForm.initial() }, "calibration");

    expect(QuizConfigForm.setSource(state, "lessons").mode).toBeNull();
  });
});

describe("the level", () => {
  test("starts on the scores when every lesson has one, and on the rating otherwise", () => {
    expect(QuizConfigForm.modeOf(withLessons(["1", "2"]), eligible(2))).toBe("existing_score");
    expect(QuizConfigForm.modeOf(withLessons(["1", "2"]), eligible(2, false))).toBe("self_rating");
    expect(QuizConfigForm.modeOf(QuizConfigForm.initial(), [])).toBe("self_rating");
  });

  test("the learner's own pick wins, whatever the lessons say", () => {
    const state = QuizConfigForm.setMode(withLessons(["1", "2"]), "calibration");

    expect(QuizConfigForm.modeOf(state, eligible(2))).toBe("calibration");
  });

  test("says which of the picked lessons have a score", () => {
    const lessons = [...eligible(1), { ...eligible(2)[1], scored: false }];

    expect(QuizConfigForm.scores(withLessons(["2", "1"]), lessons)).toEqual([false, true]);
    expect(QuizConfigForm.scores(QuizConfigForm.initial(), lessons)).toEqual([]);
  });
});

describe("the steps", () => {
  test("the source needs a topic of two letters, or a lesson", () => {
    expect(QuizConfigForm.stepReady("source", { ...QuizConfigForm.initial(), topic: " a " }, [])).toBe(false);
    expect(QuizConfigForm.stepReady("source", { ...QuizConfigForm.initial(), topic: " ab " }, [])).toBe(true);
    expect(QuizConfigForm.stepReady("source", withLessons([]), [])).toBe(false);
    expect(QuizConfigForm.stepReady("source", withLessons(["1"]), eligible(1))).toBe(true);
  });

  test("the level step needs a mode that can be used and, for a rating, its stars", () => {
    const rated = QuizConfigForm.setMode(QuizConfigForm.initial(), "self_rating");
    expect(QuizConfigForm.stepReady("level", rated, [])).toBe(false);
    expect(QuizConfigForm.stepReady("level", QuizConfigForm.setRating(rated, 5), [])).toBe(true);
    expect(QuizConfigForm.stepReady("level", QuizConfigForm.setMode(rated, "calibration"), [])).toBe(true);
    // scores asked for a lesson that has none
    const scores = QuizConfigForm.setMode(withLessons(["1"]), "existing_score");
    expect(QuizConfigForm.stepReady("level", scores, eligible(1, false))).toBe(false);
    expect(QuizConfigForm.stepReady("level", scores, eligible(1))).toBe(true);
  });

  test("the whole form is ready when every step is", () => {
    const state = { ...QuizConfigForm.initial(), topic: "Algebra" };
    expect(QuizConfigForm.ready(state, [])).toBe(false);
    expect(QuizConfigForm.ready(QuizConfigForm.setRating(state, 6), [])).toBe(true);
  });
});

describe("the request", () => {
  test("for a topic", () => {
    const state = QuizConfigForm.setRating({ ...QuizConfigForm.initial(), topic: "  Algebra ", count: 15, types: ["mcq", "msq"] }, 6);

    expect(QuizConfigForm.request(state, [])).toEqual({
      source: { type: "topic", topic: "Algebra" },
      num_questions: 15,
      types: ["mcq", "msq"],
      level: { mode: "self_rating", rating: 3 },
    });
  });

  test("for lessons, using their scores", () => {
    const request = QuizConfigForm.request(withLessons(["2", "1"], { count: 20 }), eligible(2));

    expect(request).toEqual({
      source: { type: "lessons", lesson_ids: ["2", "1"] },
      num_questions: 20,
      types: ["mcq"],
      level: { mode: "existing_score" },
    });
  });

  test("nothing while the form is incomplete", () => {
    expect(QuizConfigForm.request(QuizConfigForm.initial(), [])).toBeNull();
    expect(QuizConfigForm.request({ ...QuizConfigForm.initial(), topic: "Algebra" }, [])).toBeNull(); // no stars yet
  });
});
