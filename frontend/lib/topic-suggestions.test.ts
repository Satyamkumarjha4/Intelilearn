/**
 * Unit under test: `TopicSuggestions` (the call and the reading of its answer) and `TopicPick` (what the learner chose
 * to start with).
 *
 * Why: the suggestions come from a model, so their shape is not to be trusted: a card without a title, a page that
 * claims there is more but has nothing, or an answer that is not an object must never break the last onboarding step.
 * And "pick a card or type your own" is two inputs for one choice: if both stayed set, the quick check would start on
 * a topic the learner can't see.
 *
 * Use cases:
 * - asks for a page of suggestions (pages count from 0) with the learner's answers, and reads the topics (subject, title in the learner's language, reason) and whether
 *   there are more
 * - drops cards without a title, trims text, keeps only the first few cards of a page, and treats any other answer as
 *   an empty page with nothing more
 * - picking a card clears what was typed, and typing clears the card
 * - the topic to start is the card's title or what was typed; it can start from a card or from two typed characters
 */
import { describe, expect, test } from "bun:test";

import type { ApiClient } from "./api";
import { TopicPick, TopicSuggestions, type SuggestionAnswers } from "./topic-suggestions";

const answers: SuggestionAnswers = { education_level: "school", goal: "exam_prep", preferred_language: "hi", grade_or_year: "Class 9", field_of_study: "" };

const card = { subject: "Maths", title: "Quadratic equations", reason: "You're in Class 9" };

function fakeClient(answer: unknown) {
  const calls: { path: string; body?: unknown; method?: string }[] = [];
  const client = { request: async (path: string, options?: { body?: unknown; method?: string }) => (calls.push({ path, ...options }), answer) } as unknown as ApiClient;
  return { api: new TopicSuggestions(client), calls };
}

describe("TopicSuggestions.page", () => {
  test("asks for a page and reads the topics and whether there are more", async () => {
    const { api, calls } = fakeClient({ topics: [card], has_more: true });

    expect(await api.page(answers, 1)).toEqual({ topics: [card], hasMore: true });
    expect(calls).toEqual([{ path: "/onboarding/topic-suggestions", method: "POST", body: { ...answers, page: 1 } }]);
  });

  test("drops cards without a title, trims text and keeps the first four", async () => {
    const topics = [{ title: "  A  ", subject: " S ", reason: " R " }, { subject: "none" }, { title: "" }, { title: "B" }, { title: "C" }, { title: "D" }, { title: "E" }];
    const { api } = fakeClient({ topics, has_more: false });

    const page = await api.page(answers, 0);

    expect(page.topics.map((t) => t.title)).toEqual(["A", "B", "C", "D"]);
    expect(page.topics[0]).toEqual({ subject: "S", title: "A", reason: "R" });
    expect(page.topics[1]).toEqual({ subject: "", title: "B", reason: "" });
  });

  test.each([[null], ["nope"], [[]], [{}], [{ topics: "x" }]])("%p is an empty page with nothing more", async (answer) => {
    expect(await fakeClient(answer).api.page(answers, 0)).toEqual({ topics: [], hasMore: false });
  });

  test("a page that says there is more but has nothing says there is no more", async () => {
    expect((await fakeClient({ topics: [], has_more: true }).api.page(answers, 0)).hasMore).toBe(false);
  });
});

describe("TopicPick", () => {
  test("picking a card clears what was typed, and typing clears the card", () => {
    const typed = new TopicPick().type("Photosynthesis");
    const picked = typed.pick(card);

    expect([picked.typed, picked.selected]).toEqual(["", card]);
    expect([picked.type("Optics").selected, picked.type("Optics").typed]).toEqual([null, "Optics"]);
  });

  test("typing nothing keeps the card", () => {
    expect(new TopicPick().pick(card).type("").selected).toEqual(card);
  });

  test("the topic is the card's title or what was typed", () => {
    expect(new TopicPick().pick(card).topic()).toBe("Quadratic equations");
    expect(new TopicPick().type("  Optics ").topic()).toBe("Optics");
    expect(new TopicPick().topic()).toBe("");
  });

  test.each([["", false], ["a", false], [" a ", false], ["ab", true]])("typed %j can start: %s", (text, can) => {
    expect(new TopicPick().type(text).canStart).toBe(can);
  });

  test("a card can start, and so can nothing else", () => {
    expect(new TopicPick().pick(card).canStart).toBe(true);
    expect(new TopicPick().canStart).toBe(false);
  });

  test("a typed topic is kept to the length the API accepts", () => {
    expect(new TopicPick().type("x".repeat(300)).topic()).toHaveLength(200);
  });
});
