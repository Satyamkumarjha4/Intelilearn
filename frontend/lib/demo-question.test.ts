/**
 * Unit under test: `DemoQuestions` (reading, labelling and the built-in question) and `DemoQuestionFetcher` (asking the
 * API for a random one), the data behind the landing page's try-it card.
 *
 * Why: the card is the first thing a visitor touches, and its question now comes from the API. Whatever arrives (a
 * question with two options, a correct answer that points at nothing, an error page, a timeout, a server that is down)
 * must end in a card that works: the built-in question. A bad row typed into the admin must not break the front page.
 *
 * Use cases:
 * - a well-formed API question is read as it is
 * - a question that is malformed (not an object, wrong number of options, an answer or band out of range, a missing or
 *   malformed outcome, blank text) is refused, so the card never has to guess
 * - the label reads "<band name> · <subject> · <level label>"
 * - the built-in question is itself a valid question, with an id that no stored question can have (that it is not one of
 *   the 25 the bank starts with is checked on the backend, tests/marketing/test_seed.py, which holds the seed)
 * - asking: the request goes to the demo-question endpoint, with `exclude` when one is given, never cached, within a time
 *   limit, carrying the visitor's address when the server asks on their behalf
 * - the answer is the question, or null for anything else: a failed request, an error status, a body that is not
 *   JSON or not a question
 * - after a failed ask for another question: the built-in one, unless that is the one just seen (then nothing new)
 */
import { describe, expect, test } from "bun:test";

import { DemoQuestionFetcher, DemoQuestions } from "./demo-question";
import type { DemoQuestion } from "./types";

const good: DemoQuestion = {
  id: 7,
  subject: "Chemistry",
  level_label: "Class 7",
  band: 2,
  question: "Which of these turns blue litmus paper red?",
  options: ["Lemon juice", "Soap solution", "Baking soda solution"],
  correct_index: 0,
  outcome_right: { level: 3, level_label: "Getting there", lesson_start: "What happens when an acid meets a base." },
  outcome_wrong: { level: 1, level_label: "New to it", lesson_start: "What acids and bases are." },
};

describe("DemoQuestions.parse", () => {
  test("reads a well-formed question as it is", () => {
    expect(DemoQuestions.parse(good)).toEqual(good);
    expect(DemoQuestions.parse({ ...good, something_new: 1 })).toEqual(good); // fields the page does not know are dropped
  });

  test.each<[string, unknown]>([
    ["null", null],
    ["text", "question"],
    ["an array", [good]],
    ["no id", { ...good, id: undefined }],
    ["a text id", { ...good, id: "7" }],
    ["two options", { ...good, options: ["a", "b"] }],
    ["four options", { ...good, options: ["a", "b", "c", "d"] }],
    ["a blank option", { ...good, options: ["a", " ", "c"] }],
    ["a number as an option", { ...good, options: ["a", 2, "c"] }],
    ["an answer past the options", { ...good, correct_index: 3 }],
    ["a negative answer", { ...good, correct_index: -1 }],
    ["a fractional answer", { ...good, correct_index: 0.5 }],
    ["band 0", { ...good, band: 0 }],
    ["band 6", { ...good, band: 6 }],
    ["a blank question", { ...good, question: "  " }],
    ["a blank subject", { ...good, subject: "" }],
    ["no outcome", { ...good, outcome_right: undefined }],
    ["a level 6 outcome", { ...good, outcome_wrong: { ...good.outcome_wrong, level: 6 } }],
    ["an outcome with no lesson start", { ...good, outcome_right: { level: 3, level_label: "x" } }],
  ])("refuses %s", (_name, raw) => {
    expect(DemoQuestions.parse(raw)).toBeNull();
  });

  test("trims the texts", () => {
    expect(DemoQuestions.parse({ ...good, subject: "  Chemistry ", options: [" a", "b ", " c "] })).toMatchObject({
      subject: "Chemistry",
      options: ["a", "b", "c"],
    });
  });
});

describe("DemoQuestions.label", () => {
  test.each([
    [1, "Basics"],
    [2, "Easy"],
    [3, "Medium"],
    [4, "Hard"],
    [5, "Expert"],
  ])("band %i is named %s", (band, name) => {
    expect(DemoQuestions.label({ ...good, band })).toBe(`${name} · Chemistry · Class 7`);
  });
});

describe("DemoQuestions.fallback", () => {
  test("is a valid question that no stored question can be mistaken for", () => {
    const fallback = DemoQuestions.fallback();

    expect(DemoQuestions.parse(fallback)).toEqual(fallback);
    expect(fallback.id).toBe(0);
    expect(DemoQuestions.label(fallback)).toBe("Easy · Maths · Class 7");
    expect(fallback.options[fallback.correct_index]).toBe("3/4");
  });

  test("after a failed ask, it is the next question unless it is the one just seen", () => {
    expect(DemoQuestions.afterFailure(7)).toEqual(DemoQuestions.fallback());
    expect(DemoQuestions.afterFailure(0)).toBeNull();
  });
});

describe("DemoQuestionFetcher", () => {
  function fetcher(reply: () => Response | Promise<Response>, base = "") {
    const calls: { url: string; init: RequestInit }[] = [];
    const fake = (async (url: string, init: RequestInit) => (calls.push({ url, init }), reply())) as unknown as typeof fetch;
    return { fetcher: new DemoQuestionFetcher(fake, base, 1500), calls };
  }
  const ok = (body: unknown) => () => Response.json(body);

  test("asks the demo-question endpoint, never cached, within a time limit", async () => {
    const { fetcher: ask, calls } = fetcher(ok(good), "http://backend:8000");

    expect(await ask.fetch()).toEqual(good);
    expect(calls[0].url).toBe("http://backend:8000/api/landing/demo-question");
    expect(calls[0].init.cache).toBe("no-store");
    expect(calls[0].init.signal).toBeInstanceOf(AbortSignal);
  });

  test("passes exclude when given, and the visitor's address when asking for them", async () => {
    const { fetcher: ask, calls } = fetcher(ok(good));

    await ask.fetch({ exclude: 7, clientIp: "203.0.113.9" });

    expect(calls[0].url).toBe("/api/landing/demo-question?exclude=7");
    expect(calls[0].init.headers).toEqual({ "x-forwarded-for": "203.0.113.9" });
  });

  test("a question exclude of 0 (the built-in one) is passed too", async () => {
    const { fetcher: ask, calls } = fetcher(ok(good));
    await ask.fetch({ exclude: 0 });

    expect(calls[0].url).toBe("/api/landing/demo-question?exclude=0");
  });

  test.each<[string, () => Response | Promise<Response>]>([
    ["a 404", () => new Response("{}", { status: 404 })],
    ["a 429", () => Response.json({ code: "throttled" }, { status: 429 })],
    ["a 500", () => new Response("oops", { status: 500 })],
    ["a body that is not JSON", () => new Response("<html>", { status: 200 })],
    ["a body that is not a question", () => Response.json({ id: 1 })],
    ["a request that fails", () => Promise.reject(new Error("connection refused"))],
  ])("gives null for %s", async (_name, reply) => {
    expect(await fetcher(reply).fetcher.fetch()).toBeNull();
  });
});
