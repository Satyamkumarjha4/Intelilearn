/**
 * Unit under test: `QuestionInputs`, which says how each kind of question is answered (the widget, the label, the hint, the
 * keys) so the test screen and the practice sheet agree.
 *
 * Why: a multiple-select question answered like a single choice loses the learner's picks, and a number box that rejects
 * "4.0" because the hint said "whole number" would turn a hint into a rule. The logic lives here, not in the components.
 *
 * Use cases:
 * - every kind of question maps to one widget and one label, a group of options is called "Answers" and a box "Your
 *   answer" for a screen reader, and an unknown kind falls back to a text box
 * - a multiple-select question toggles options, keeps them sorted, and is unanswered when none is left
 * - a multiple-select question says "Choose all that apply"; other kinds say nothing unless they have a hint
 * - a number question hints how many decimals (a whole number, 1 place, 2 places) and says nothing without a precision
 * - the number keypad is the digits one for whole numbers and the decimal one otherwise
 * - keys 1 to 9 and letters pick an option of a multiple-choice question and toggle one of a multiple-select question,
 *   and mean nothing for an option that is not there or for other kinds
 * - blank text, an empty selection and a missing answer are unanswered; any option, even the first, is an answer
 * - untouched starter code is not an answer
 * - a short or long answer that names a language is answered in the code editor, with its own label and hint; one that does
 *   not name one, and every other kind, keeps its own input
 */
import { describe, expect, test } from "bun:test";

import { QuestionInputs } from "@/lib/question-inputs";

describe("QuestionInputs.of", () => {
  test.each([
    ["mcq", "choice", "Multiple choice"],
    ["msq", "multi", "Multiple select"],
    ["numerical", "number", "Number"],
    ["short_answer", "text", "Short answer"],
    ["long_answer", "paragraph", "Written answer"],
    ["code", "code", "Code"],
  ])("%s is a %s with the label %s", (type, widget, label) => {
    expect(QuestionInputs.of(type).widget).toBe(widget as never);
    expect(QuestionInputs.of(type).label).toBe(label);
  });

  test("a group of options is called Answers and a box Your answer, for a screen reader", () => {
    expect(QuestionInputs.mcq.answerLabel).toBe("Answers");
    expect(QuestionInputs.msq.answerLabel).toBe("Answers");
    expect(QuestionInputs.number.answerLabel).toBe("Your answer");
    expect(QuestionInputs.long.answerLabel).toBe("Your answer");
  });

  test("a kind it does not know is answered in a text box", () => {
    expect(QuestionInputs.of("essay").widget).toBe("paragraph");
  });
});

describe("multiple select", () => {
  const { msq } = QuestionInputs;

  test("toggling adds an option, keeps them sorted and takes one away again", () => {
    expect(msq.toggle(undefined, 2)).toEqual([2]);
    expect(msq.toggle([2], 0)).toEqual([0, 2]);
    expect(msq.toggle([0, 2], 2)).toEqual([0]);
  });

  test("taking the last option away leaves the card unanswered", () => {
    expect(msq.toggle([1], 1)).toBeNull();
  });

  test("a stray answer of another kind starts a fresh selection", () => {
    expect(msq.toggle("text", 1)).toEqual([1]);
    expect(msq.toggle(3, 1)).toEqual([1]);
  });

  test("it knows which options are picked", () => {
    expect(msq.isPicked([0, 2], 2)).toBe(true);
    expect(msq.isPicked([0, 2], 1)).toBe(false);
    expect(msq.isPicked(undefined, 0)).toBe(false);
    expect(msq.isPicked(1, 1)).toBe(false);
  });

  test("it says to choose all that apply", () => {
    expect(msq.instruction()).toBe("Choose all that apply");
  });
});

describe("number", () => {
  const { number } = QuestionInputs;

  test.each([
    [0, "Give a whole number"],
    [1, "Give your answer to 1 decimal place"],
    [2, "Give your answer to 2 decimal places"],
    [6, "Give your answer to 6 decimal places"],
  ])("a precision of %i says %s", (decimal_precision, text) => {
    expect(number.instruction({ type: "numerical", decimal_precision })).toBe(text);
  });

  test("without a precision there is no hint", () => {
    expect(number.instruction({ type: "numerical" })).toBeNull();
  });

  test("whole numbers get the digits keypad and the rest the decimal one", () => {
    expect(number.inputMode({ type: "numerical", decimal_precision: 0 })).toBe("numeric");
    expect(number.inputMode({ type: "numerical", decimal_precision: 2 })).toBe("decimal");
    expect(number.inputMode({ type: "numerical" })).toBe("decimal");
  });

  test("the hint is not a rule: any answer counts as an answer", () => {
    expect(number.isAnswered("4.0")).toBe(true);
    expect(number.isAnswered("4.123456")).toBe(true);
  });
});

describe("keys", () => {
  const question = { type: "mcq" as const, options: ["a", "b", "c", "d"] };

  test.each([
    ["1", 0],
    ["4", 3],
    ["a", 0],
    ["d", 3],
  ])("%s picks option %i of a multiple-choice question", (key, index) => {
    expect(QuestionInputs.mcq.onKey(question, undefined, key)).toBe(index);
  });

  test.each(["5", "e", "z", "Enter", "0", "ab"])("%s is nothing for a four-option question", (key) => {
    expect(QuestionInputs.mcq.onKey(question, undefined, key)).toBeUndefined();
  });

  test("a key toggles an option of a multiple-select question", () => {
    const msq = { type: "msq" as const, options: ["a", "b", "c", "d", "e"] };

    expect(QuestionInputs.msq.onKey(msq, [0], "c")).toEqual([0, 2]);
    expect(QuestionInputs.msq.onKey(msq, [0, 2], "3")).toEqual([0]);
    expect(QuestionInputs.msq.onKey(msq, [0], "q")).toBeUndefined();
  });

  test("the other kinds do not use keys", () => {
    expect(QuestionInputs.number.onKey({ type: "numerical" }, undefined, "1")).toBeUndefined();
    expect(QuestionInputs.short.onKey({ type: "short_answer" }, undefined, "a")).toBeUndefined();
  });
});

describe("answered", () => {
  test.each([
    [undefined, false],
    ["", false],
    ["   ", false],
    [[], false],
    [0, true],
    [3, true],
    ["words", true],
    [[0], true],
  ])("%p is answered: %p", (answer, answered) => {
    expect(QuestionInputs.long.isAnswered(answer as never)).toBe(answered);
  });
});

describe("code", () => {
  const question = { type: "code" as const, starter_code: "def f():\n    pass\n" };

  test("the box starts with the starter code and then shows what the learner wrote", () => {
    expect(QuestionInputs.code.text(question, undefined)).toBe("def f():\n    pass\n");
    expect(QuestionInputs.code.text(question, "return 1")).toBe("return 1");
    expect(QuestionInputs.code.text({ type: "code" }, undefined)).toBe("");
  });

  test("untouched starter code is not an answer", () => {
    expect(QuestionInputs.code.isStarter(question, "def f():\n    pass")).toBe(true);
    expect(QuestionInputs.code.isStarter(question, "def f(): return 1")).toBe(false);
  });
});

describe("a written answer about code", () => {
  test.each(["short_answer", "long_answer"] as const)("a %s that names a language is answered in the code editor", (type) => {
    const input = QuestionInputs.forQuestion({ type, language: "Python 3" });

    expect(input.widget).toBe("code");
    expect(input.label).toBe("Code answer");
    expect(input.answerLabel).toBe("Your code");
    expect(input.instruction({ type })).toBe("Write your code in the editor");
  });

  test.each(["short_answer", "long_answer"] as const)("a %s with no language keeps its text box", (type) => {
    expect(QuestionInputs.forQuestion({ type }).widget).toBe(QuestionInputs.of(type).widget);
    expect(QuestionInputs.forQuestion({ type, language: "  " }).widget).toBe(QuestionInputs.of(type).widget);
  });

  test("other kinds keep their own input whatever language they carry", () => {
    expect(QuestionInputs.forQuestion({ type: "mcq", language: "python" })).toBe(QuestionInputs.mcq);
    expect(QuestionInputs.forQuestion({ type: "code", language: "python" })).toBe(QuestionInputs.code);
  });

  test("an empty box is not an answer, and neither is starter code nobody changed", () => {
    const input = QuestionInputs.forQuestion({ type: "short_answer", language: "python" });

    expect(input.isAnswered("")).toBe(false);
    expect(input.isAnswered("print(1)")).toBe(true);
  });
});
