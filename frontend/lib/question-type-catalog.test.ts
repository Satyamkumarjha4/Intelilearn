/**
 * Unit under test: `QuestionTypeCatalog`, the kinds of question the quiz wizard offers.
 *
 * Why: the server refuses a short answer in a five-question quiz and a number question for a topic that is not about
 * calculation. The wizard must hide exactly what the server would refuse (showing it would send learners into an
 * error), and must never leave a quiz asking nothing or asking something that was hidden after it was picked.
 *
 * Use cases:
 * - offers multiple choice and multiple select always, number questions unless the topic was judged not to be about
 *   calculation, and short and written answers from ten questions
 * - offers every kind its count allows for a topic nobody judged
 * - keeps the kinds in the standard order
 * - drops a picked kind that is no longer offered (the count went down, or the topic changed) and falls back to multiple
 *   choice when nothing is left
 * - picks and drops a kind, but never drops the last one
 * - explains what is missing: the written kinds below ten questions, the number questions for a topic that is not maths
 */
import { describe, expect, test } from "bun:test";

import { QuestionTypeCatalog } from "./question-type-catalog";

const ids = (options: { id: string }[]) => options.map((o) => o.id);
const MATHS = { numerical: true, code: false };
const HISTORY = { numerical: false, code: false };

describe("which kinds are offered", () => {
  test.each([
    [MATHS, 5, ["mcq", "msq", "numerical"]],
    [HISTORY, 5, ["mcq", "msq"]],
    [MATHS, 10, ["mcq", "msq", "numerical", "short_answer", "long_answer"]],
    [HISTORY, 30, ["mcq", "msq", "short_answer", "long_answer"]],
    [null, 5, ["mcq", "msq", "numerical"]],
    [null, 15, ["mcq", "msq", "numerical", "short_answer", "long_answer"]],
  ] as const)("topic %p with %p questions offers %p", (kinds, count, expected) => {
    expect(ids(QuestionTypeCatalog.offered(kinds, count))).toEqual([...expected]);
  });

  test("every kind has words a learner can read", () => {
    for (const option of QuestionTypeCatalog.ALL) {
      expect(option.label.length).toBeGreaterThan(3);
      expect(option.hint.endsWith(".")).toBe(true);
      expect(QuestionTypeCatalog.label(option.id)).toBe(option.label);
    }
  });
});

describe("keeping a pick valid", () => {
  test("drops what is no longer offered and keeps the order", () => {
    expect(QuestionTypeCatalog.keep(["long_answer", "mcq", "numerical"], MATHS, 5)).toEqual(["mcq", "numerical"]);
    expect(QuestionTypeCatalog.keep(["mcq", "numerical"], HISTORY, 15)).toEqual(["mcq"]);
  });

  test("falls back to multiple choice when nothing is left", () => {
    expect(QuestionTypeCatalog.keep(["short_answer"], MATHS, 5)).toEqual(["mcq"]);
    expect(QuestionTypeCatalog.keep([], MATHS, 5)).toEqual(["mcq"]);
  });
});

describe("picking", () => {
  test("adds a kind in the standard order and drops one that is picked", () => {
    expect(QuestionTypeCatalog.toggle(["mcq"], "numerical")).toEqual(["mcq", "numerical"]);
    expect(QuestionTypeCatalog.toggle(["mcq", "numerical"], "msq")).toEqual(["mcq", "msq", "numerical"]);
    expect(QuestionTypeCatalog.toggle(["mcq", "msq"], "mcq")).toEqual(["msq"]);
  });

  test("never drops the last kind", () => {
    expect(QuestionTypeCatalog.toggle(["msq"], "msq")).toEqual(["msq"]);
  });
});

describe("saying why", () => {
  test("explains the written kinds below ten questions first, then a topic that is not about calculation", () => {
    expect(QuestionTypeCatalog.note(MATHS, 5)).toBe("Short and written answers need 10 or more questions.");
    expect(QuestionTypeCatalog.note(HISTORY, 10)).toBe("This topic isn't about calculating, so there are no number questions.");
    expect(QuestionTypeCatalog.note(MATHS, 10)).toBeNull();
    expect(QuestionTypeCatalog.note(null, 20)).toBeNull();
  });
});
