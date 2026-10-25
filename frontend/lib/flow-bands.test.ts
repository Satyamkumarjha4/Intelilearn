/**
 * Unit under test: `FlowBands`, which works out where each quick-check score sends a learner from the lesson settings.
 *
 * Why: three settings (questions per level, the "foundations first" cut-off, whether mastery needs a perfect score)
 * decide the learner's route, and no one can see what they add up to from the numbers alone. The Lesson settings page
 * shows the result live from the unsaved form, so a cut-off that overlaps mastery, or one that leaves no score for the
 * regular lesson, is seen before it is saved. The zones must follow `RoutingPolicy` on the server exactly.
 *
 * Use cases:
 * - the quick check has five levels, so the total is five times the questions per level
 * - a score is foundations at or below the cut-off, mastery from the mastery minimum, and the lesson in between
 * - mastery needs a perfect score, or one less when that is switched off (and then the hardest questions must be right)
 * - mastery wins where the cut-off reaches it, and a cut-off past the total puts every score before mastery in foundations
 * - the legend states the ranges in words, with single scores written alone and empty zones left out
 * - a settings combination that leaves no score for the lesson is called out
 * - it agrees with the thresholds the API reports for the same settings
 */
import { describe, expect, test } from "bun:test";

import { FlowBands, type BandSettings } from "./flow-bands";

const defaults: BandSettings = { diagnostic_questions_per_band: 2, prereq_trigger_max_correct: 2, mastery_requires_all_correct: true, prerequisite_question_count: 5 };
const zones = (settings: Partial<BandSettings>) => FlowBands.of({ ...defaults, ...settings }).cells.map((c) => c.zone);

describe("total", () => {
  test("is five levels times the questions per level", () => {
    expect(FlowBands.of(defaults).total).toBe(10);
    expect(FlowBands.of({ ...defaults, diagnostic_questions_per_band: 4 }).total).toBe(20);
    expect(FlowBands.of({ ...defaults, diagnostic_questions_per_band: 1 }).total).toBe(5);
  });
});

describe("cells", () => {
  test("one per possible score, 0 to the total", () => {
    const { cells } = FlowBands.of(defaults);

    expect(cells).toHaveLength(11);
    expect(cells.map((c) => c.score)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  test("foundations up to the cut-off, the lesson after it, study sheets for a perfect score", () => {
    expect(zones({})).toEqual(["foundations", "foundations", "foundations", "lesson", "lesson", "lesson", "lesson", "lesson", "lesson", "lesson", "study"]);
  });

  test("with perfect score off, one less than perfect is mastery too", () => {
    expect(zones({ mastery_requires_all_correct: false }).slice(8)).toEqual(["lesson", "study", "study"]);
  });

  test("a cut-off that reaches the mastery minimum gives way to mastery", () => {
    expect(zones({ prereq_trigger_max_correct: 10 })).toEqual([...Array(10).fill("foundations"), "study"]);
    expect(zones({ prereq_trigger_max_correct: 9, mastery_requires_all_correct: false }).slice(8)).toEqual(["foundations", "study", "study"]);
  });

  test("a cut-off of nothing sends only a score of zero to the foundations", () => {
    expect(zones({ prereq_trigger_max_correct: 0 }).slice(0, 3)).toEqual(["foundations", "lesson", "lesson"]);
  });
});

describe("legend", () => {
  const legend = (settings: Partial<BandSettings> = {}) => FlowBands.of({ ...defaults, ...settings }).legend;

  test("states each range in words", () => {
    expect(legend()).toEqual([
      { zone: "foundations", range: "0–2", text: "Foundations check (5 questions), then a lesson that starts with the basics" },
      { zone: "lesson", range: "3–9", text: "Lesson at their level" },
      { zone: "study", range: "10", text: "Study sheets, no lesson" },
    ]);
  });

  test("a range of one score is written as that score", () => {
    expect(legend({ prereq_trigger_max_correct: 0 })[0].range).toBe("0");
  });

  test("study sheets from one below the total say the hardest questions must be right", () => {
    const study = legend({ mastery_requires_all_correct: false }).find((l) => l.zone === "study")!;

    expect(study.range).toBe("9–10");
    expect(study.text).toBe("Study sheets, no lesson (the hardest questions must all be right)");
  });

  test("leaves out a zone no score reaches", () => {
    expect(legend({ prereq_trigger_max_correct: 9 }).map((l) => l.zone)).toEqual(["foundations", "study"]);
    expect(legend({ prereq_trigger_max_correct: 9 })[0].range).toBe("0–9");
  });

  test("uses the length of the foundations check", () => {
    expect(legend({ prerequisite_question_count: 8 })[0].text).toContain("(8 questions)");
  });
});

describe("notice", () => {
  test("says so when no score gets the regular lesson", () => {
    expect(FlowBands.of({ ...defaults, prereq_trigger_max_correct: 9 }).notice).toBe("With these settings no score gets the regular lesson.");
  });

  test("says nothing when the settings are sensible", () => {
    expect(FlowBands.of(defaults).notice).toBeNull();
  });
});

describe("thresholds", () => {
  test("match what the API reports for the same settings", () => {
    const bands = FlowBands.of(defaults);
    const reported = { questions_total: 10, foundations_max: 2, mastery_min: 10 };

    expect(FlowBands.thresholds(defaults)).toEqual(reported);
    expect(bands.masteryMin).toBe(reported.mastery_min);
    expect(FlowBands.thresholds({ ...defaults, mastery_requires_all_correct: false }).mastery_min).toBe(9);
  });
});
