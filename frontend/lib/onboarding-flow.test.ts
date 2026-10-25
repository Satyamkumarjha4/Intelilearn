/**
 * Unit under test: `OnboardingFlow` (the state of the five-step setup), `OnboardingStore` (its place kept in
 * `sessionStorage`) and `OnboardingChoices` (the tiles, matched to what the API offers).
 *
 * Why: this is the first thing a new learner does. A step that lets them continue without the answer the lessons need,
 * a follow-up question whose answer lands in the wrong profile field (or is kept after they change their mind), a
 * refresh that loses their place, or a tile for a value the API no longer accepts would each break the profile.
 *
 * Use cases:
 * - starts on step 1 with English chosen; each step needs its own answer (study level and, where asked, class or year;
 *   learning style; goal; language) before Continue, and the follow-up field is optional
 * - each study level asks its own follow-up (class, year, programme year, field of work, a focus) and the answers
 *   land in grade_or_year and field_of_study
 * - changing the study level forgets answers that only made sense for the old one
 * - Back is allowed and never goes before step 1; Continue never goes past step 5 or past an unanswered step; the
 *   direction of the last move is known (for the slide)
 * - the profile to save has what was answered, trimmed, without a name
 * - a saved profile pre-fills the flow, and the flow says when everything is answered
 * - the summary names what the suggestions are based on
 * - the place and answers survive a refresh; rubbish in storage, or no storage, starts fresh
 * - the tiles are the usual copy for the values the API offers, with any new value shown under its API label
 */
import { describe, expect, test } from "bun:test";

import { OnboardingChoices, OnboardingFlow, OnboardingStore } from "./onboarding-flow";

const at = (changes: Parameters<OnboardingFlow["with"]>[0] = {}, step = 1) => new OnboardingFlow().with(changes).goTo(step);

describe("start", () => {
  test("begins on step 1 with English chosen and nothing else", () => {
    const flow = new OnboardingFlow();

    expect([flow.step, flow.answers.preferred_language, flow.answers.education_level, flow.canContinue]).toEqual([1, "en", "", false]);
    expect(flow.direction).toBe("forward");
  });
});

describe("what each step needs", () => {
  test.each([
    [{ education_level: "professional" }, true],
    [{ education_level: "self_learner" }, true],
    [{ education_level: "school" }, false],
    [{ education_level: "school", grade_or_year: "Class 9" }, true],
    [{ education_level: "undergraduate" }, false],
    [{ education_level: "undergraduate", grade_or_year: "2nd year" }, true],
    [{ education_level: "postgraduate", grade_or_year: "Research" }, true],
    [{}, false],
  ] as const)("step 1 with %j: %s", (changes, can) => {
    expect(at(changes).canContinue).toBe(can);
  });

  test("steps 2 to 4 need a learning style, a goal and a language", () => {
    expect(at({}, 2).canContinue).toBe(false);
    expect(at({ learning_preference: "visual" }, 2).canContinue).toBe(true);
    expect(at({}, 3).canContinue).toBe(false);
    expect(at({ goal: "exam_prep" }, 3).canContinue).toBe(true);
    expect(at({}, 4).canContinue).toBe(true);
    expect(at({ preferred_language: "" }, 4).canContinue).toBe(false);
  });

  test("step 5 has its own buttons, so there is nothing to continue to", () => {
    expect(at({}, 5).canContinue).toBe(false);
  });
});

describe("follow-up questions", () => {
  test.each([
    ["school", "Which class are you in?", ["Class 6", "Class 7", "Class 8", "Class 9", "Class 10", "Class 11", "Class 12"], null],
    ["undergraduate", "Which year?", ["1st year", "2nd year", "3rd year", "4th year"], "What are you studying?"],
    ["postgraduate", "Which year?", ["1st year", "2nd year", "Research"], "What are you studying?"],
    ["professional", null, [], "What field do you work in?"],
    ["self_learner", null, [], "Anything you're focusing on? (optional)"],
  ] as const)("%s", (level, grade, grades, field) => {
    const ask = OnboardingFlow.followUp(level);

    expect([ask.gradeQuestion, ask.grades, ask.fieldQuestion]).toEqual([grade, [...grades], field]);
  });

  test("an unchosen level asks nothing", () => {
    expect(OnboardingFlow.followUp("")).toEqual({ gradeQuestion: null, grades: [], fieldQuestion: null });
  });

  test("the answers land in grade_or_year and field_of_study", () => {
    const flow = new OnboardingFlow().with({ education_level: "undergraduate" }).with({ grade_or_year: "3rd year", field_of_study: "Physics" });

    expect([flow.answers.grade_or_year, flow.answers.field_of_study]).toEqual(["3rd year", "Physics"]);
  });
});

describe("changing the study level", () => {
  test("forgets a class or year that belongs to the old one, and keeps the field", () => {
    const flow = new OnboardingFlow().with({ education_level: "school", grade_or_year: "Class 9", field_of_study: "Maths" }).with({ education_level: "undergraduate" });

    expect([flow.answers.grade_or_year, flow.answers.field_of_study]).toEqual(["", "Maths"]);
  });

  test("keeps a year that makes sense for the new level too, and forgets a field the new level never asks", () => {
    const keep = new OnboardingFlow().with({ education_level: "undergraduate", grade_or_year: "2nd year" }).with({ education_level: "postgraduate" });
    const drop = new OnboardingFlow().with({ education_level: "professional", field_of_study: "Law" }).with({ education_level: "school" });

    expect(keep.answers.grade_or_year).toBe("2nd year");
    expect(drop.answers.field_of_study).toBe("");
  });

  test("choosing the same level again changes nothing", () => {
    const flow = new OnboardingFlow().with({ education_level: "school", grade_or_year: "Class 9" }).with({ education_level: "school" });

    expect(flow.answers.grade_or_year).toBe("Class 9");
  });
});

describe("moving", () => {
  test("Continue moves on only when the step is answered, and never past step 5", () => {
    const flow = new OnboardingFlow();

    expect(flow.next().step).toBe(1);
    expect(flow.with({ education_level: "professional" }).next().step).toBe(2);
    expect(at({}, 5).next().step).toBe(5);
  });

  test("Back is allowed, never before step 1, and the direction is remembered", () => {
    const flow = at({ education_level: "professional", learning_preference: "mixed" }, 3);

    expect(flow.back().step).toBe(2);
    expect(flow.back().direction).toBe("back");
    expect(flow.back().next().direction).toBe("forward");
    expect(new OnboardingFlow().back().step).toBe(1);
  });

  test("goTo is kept within the five steps", () => {
    expect([new OnboardingFlow().goTo(9).step, new OnboardingFlow().goTo(-3).step]).toEqual([5, 1]);
  });

  test("it does not change the flow it started from", () => {
    const flow = new OnboardingFlow();
    flow.with({ education_level: "school" });

    expect(flow.answers.education_level).toBe("");
  });
});

describe("the profile to save", () => {
  test("has what was answered, trimmed, and no name", () => {
    const flow = new OnboardingFlow().with({
      education_level: "undergraduate", grade_or_year: "2nd year", field_of_study: "  Physics ", learning_preference: "visual", goal: "exam_prep", preferred_language: "hi", notes: " exam in May ",
    });

    expect(flow.profile()).toEqual({
      education_level: "undergraduate", grade_or_year: "2nd year", field_of_study: "Physics", learning_preference: "visual", goal: "exam_prep", preferred_language: "hi", notes: "exam in May",
    });
  });

  test("keeps the notes within the limit", () => {
    expect(new OnboardingFlow().with({ notes: "x".repeat(3000) }).profile().notes).toHaveLength(2000);
  });
});

describe("suggestion answers", () => {
  test("are the answers the server picks topics from, trimmed, without notes or learning style", () => {
    const flow = new OnboardingFlow().with({ education_level: "school", grade_or_year: "Class 9", goal: "exam_prep", preferred_language: "hi", learning_preference: "visual", notes: "n", field_of_study: " Maths " });

    expect(flow.suggestionAnswers()).toEqual({ education_level: "school", goal: "exam_prep", preferred_language: "hi", grade_or_year: "Class 9", field_of_study: "Maths" });
  });
});

describe("summary", () => {
  test("names what the suggestions are based on", () => {
    const flow = new OnboardingFlow().with({ education_level: "school", grade_or_year: "Class 9", goal: "exam_prep", preferred_language: "hi" });

    expect(flow.summary()).toEqual(["School · Class 9", "Exam prep", "हिन्दी"]);
  });

  test("leaves out what is not known, and joins the field when there is no class or year", () => {
    expect(new OnboardingFlow().summary()).toEqual(["English"]);
    expect(new OnboardingFlow().with({ education_level: "professional", field_of_study: "Law" }).summary()[0]).toBe("Working · Law");
    expect(new OnboardingFlow().with({ education_level: "self_learner" }).summary()[0]).toBe("Self-learner");
  });
});

describe("from a saved profile", () => {
  test("holds what the profile says, and English where it says no language", () => {
    const flow = OnboardingFlow.fromProfile({ education_level: "school", grade_or_year: "Class 9", preferred_language: "", goal: "exam_prep", notes: 4 as never });

    expect([flow.answers.education_level, flow.answers.grade_or_year, flow.answers.preferred_language, flow.answers.goal, flow.answers.notes]).toEqual(["school", "Class 9", "en", "exam_prep", ""]);
    expect(flow.step).toBe(1);
  });

  test("is complete only when steps 1 to 4 are all answered", () => {
    expect(OnboardingFlow.fromProfile({}).complete).toBe(false);
    expect(OnboardingFlow.fromProfile({ education_level: "professional", learning_preference: "mixed" }).complete).toBe(false);
    expect(OnboardingFlow.fromProfile({ education_level: "professional", learning_preference: "mixed", goal: "exam_prep" }).complete).toBe(true);
  });
});

describe("OnboardingStore", () => {
  const memory = () => {
    const data: Record<string, string> = {};
    return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v), removeItem: (k: string) => void delete data[k] };
  };

  test("keeps the place and the answers, and forgets them on clear", () => {
    const storage = memory();
    const flow = at({ education_level: "school", grade_or_year: "Class 9", learning_preference: "reading" }, 3);
    new OnboardingStore(storage).save(flow);

    const back = new OnboardingStore(storage).load();
    expect([back?.step, back?.answers.grade_or_year, back?.answers.learning_preference]).toEqual([3, "Class 9", "reading"]);
    new OnboardingStore(storage).clear();
    expect(new OnboardingStore(storage).load()).toBeNull();
  });

  test("a place that does not match the answers is pulled back to the first step that is missing one", () => {
    const storage = memory();
    storage.setItem("socra.onboarding", JSON.stringify({ step: 4, answers: { education_level: "school" } }));

    expect(new OnboardingStore(storage).load()?.step).toBe(1);
  });

  test.each([["not json"], ["[]"], ["null"], ['{"step":"x"}'], ['{"step":2,"answers":5}']])("rubbish (%s) starts fresh", (raw) => {
    const storage = memory();
    storage.setItem("socra.onboarding", raw);

    expect(new OnboardingStore(storage).load()).toBeNull();
  });

  test("odd values in the answers are dropped", () => {
    const storage = memory();
    storage.setItem("socra.onboarding", JSON.stringify({ step: 1, answers: { education_level: 7, notes: { a: 1 }, goal: "exam_prep", extra: "x" } }));

    const flow = new OnboardingStore(storage).load();
    expect([flow?.answers.education_level, flow?.answers.notes, flow?.answers.goal]).toEqual(["", "", "exam_prep"]);
  });

  test("works without storage and with storage that throws", () => {
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("full"); }, removeItem: () => { throw new Error("blocked"); } };
    for (const storage of [null, broken]) {
      const store = new OnboardingStore(storage);
      expect(store.load()).toBeNull();
      expect(() => store.save(new OnboardingFlow())).not.toThrow();
      expect(() => store.clear()).not.toThrow();
    }
  });
});

describe("OnboardingChoices", () => {
  const api = [{ value: "visual", label: "Visual" }, { value: "mixed", label: "Mix" }, { value: "telepathy", label: "Telepathy" }];
  const copy = [{ value: "visual", label: "Seeing it", description: "d" }, { value: "reading", label: "Reading it", description: "d" }, { value: "mixed", label: "A mix", description: "d" }];

  test("are the usual copy for the values the API offers, in the copy's order", () => {
    expect(OnboardingChoices.merge(copy, api).map((c) => c.value)).toEqual(["visual", "mixed", "telepathy"]);
  });

  test("a value only the API knows shows under its API label, with no description", () => {
    expect(OnboardingChoices.merge(copy, api).at(-1)).toEqual({ value: "telepathy", label: "Telepathy", description: "" });
  });

  test("with no API answer yet, the usual copy is shown", () => {
    expect(OnboardingChoices.merge(copy, null).map((c) => c.value)).toEqual(["visual", "reading", "mixed"]);
  });
});
