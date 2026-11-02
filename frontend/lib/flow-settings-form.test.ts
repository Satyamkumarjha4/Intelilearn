/**
 * Unit under test: `FlowSettingsForm`, the Lesson settings page's form: text boxes in, a validated patch out.
 *
 * Why: a number box holds text while someone types ("", "1e3", "2.5"), and the page must check it, show what is wrong
 * next to the box, and send only what changed. The API rejects values the admin would reject; checking them here as
 * well saves a round trip, and catches two settings that contradict each other (a Fail line at or above the Excellent
 * line, a cut-off above the number of questions).
 *
 * Use cases:
 * - turns the saved settings into form text and back
 * - checks each number against its range and says what is wrong in plain words
 * - checks pairs of settings against each other (the Fail and Excellent lines, cut-off and questions)
 * - leaves out the test size of the old settings: the test is fixed now, so it is neither shown nor sent
 * - sends only the fields that changed, as numbers, and nothing when nothing changed
 * - tells which fields are unsaved
 * - uses the saved value where a box holds something unusable, so the live preview never breaks while typing
 * - toggles a media source or licence without touching values the page does not list
 * - turns the API's refusal into a message per field
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { FlowSettingsForm, type FlowForm } from "./flow-settings-form";
import type { FlowSettingsValues } from "./types";

const saved: FlowSettingsValues = {
  diagnostic_questions_per_band: 2,
  prerequisite_question_count: 5,
  prereq_trigger_max_correct: 2,
  mastery_requires_all_correct: true,
  max_interactives_per_page: 3,
  band_fail_below: 30,
  band_excellent_above: 90,
  question_batch_size: 5,
  batch_max_long: 1,
  batch_max_short: 2,
  retakes_per_day: 3,
  quiz_max_source_lessons: 10,
  quiz_source_token_budget: 1500,
  calibration_questions: 5,
  alignment_min_score: 3,
  alignment_max_rounds: 2,
  render_check_max_rounds: 2,
  max_auto_runtime_repairs: 2,
  media_sources: ["wikimedia", "openverse"],
  allowed_media_licenses: ["cc0", "pdm", "cc-by", "cc-by-sa"],
};
const form = (patch: Partial<FlowForm> = {}): FlowForm => ({ ...FlowSettingsForm.fromSettings(saved), ...patch });

describe("fromSettings", () => {
  test("numbers become text and the rest is copied", () => {
    const values = FlowSettingsForm.fromSettings(saved);

    expect(values.diagnostic_questions_per_band).toBe("2");
    expect(values.retakes_per_day).toBe("3");
    expect(values.mastery_requires_all_correct).toBe(true);
    expect(values.media_sources).toEqual(["wikimedia", "openverse"]);
  });

  test("does not share the lists with the settings", () => {
    const values = FlowSettingsForm.fromSettings(saved);
    values.media_sources.push("giphy");

    expect(saved.media_sources).toEqual(["wikimedia", "openverse"]);
  });
});

describe("errors", () => {
  test("untouched settings have none", () => {
    expect(FlowSettingsForm.errors(form())).toEqual({});
  });

  test.each([
    ["diagnostic_questions_per_band", "", "Enter a whole number."],
    ["diagnostic_questions_per_band", "2.5", "Enter a whole number."],
    ["diagnostic_questions_per_band", "abc", "Enter a whole number."],
    ["diagnostic_questions_per_band", "0", "Enter a number from 1 to 4."],
    ["diagnostic_questions_per_band", "5", "Enter a number from 1 to 4."],
    ["prerequisite_question_count", "11", "Enter a number from 1 to 10."],
    ["alignment_min_score", "6", "Enter a number from 1 to 5."],
    ["retakes_per_day", "0", "Enter a number from 1 to 50."],
    ["quiz_max_source_lessons", "11", "Enter a number from 1 to 10."],
    ["quiz_source_token_budget", "100", "Enter a number from 200 to 6000."],
    ["calibration_questions", "2", "Enter a number from 3 to 7."],
    ["question_batch_size", "4", "Enter a number from 5 to 10."],
    ["question_batch_size", "11", "Enter a number from 5 to 10."],
    ["band_excellent_above", "101", "Enter a number from 0 to 100."],
    ["alignment_max_rounds", "-1", "Enter a whole number."],
    ["alignment_max_rounds", "40000", "Enter a number from 0 to 32767."],
  ])("%s = %j: %s", (field, text, message) => {
    expect(FlowSettingsForm.errors(form({ [field]: text }))[field as keyof FlowSettingsValues]).toBe(message);
  });

  test("spaces around a number are fine", () => {
    expect(FlowSettingsForm.errors(form({ retakes_per_day: " 4 " }))).toEqual({});
  });

  test("a Fail line at or above the Excellent line is called out on the Fail line", () => {
    expect(FlowSettingsForm.errors(form({ band_fail_below: "90" })).band_fail_below).toBe("Must be below the Excellent line (90%).");
    expect(FlowSettingsForm.errors(form({ band_fail_below: "95" })).band_fail_below).toBe("Must be below the Excellent line (90%).");
    expect(FlowSettingsForm.errors(form({ band_fail_below: "89" }))).toEqual({});
  });

  test("a cut-off above the number of questions is called out", () => {
    expect(FlowSettingsForm.errors(form({ prereq_trigger_max_correct: "11" })).prereq_trigger_max_correct).toBe("The quick check has only 10 questions.");
    expect(FlowSettingsForm.errors(form({ prereq_trigger_max_correct: "10" }))).toEqual({});
  });

  test("fewer questions per level can leave the cut-off too high", () => {
    const errors = FlowSettingsForm.errors(form({ diagnostic_questions_per_band: "1", prereq_trigger_max_correct: "7" }));

    expect(errors.prereq_trigger_max_correct).toBe("The quick check has only 5 questions.");
  });

  test("a pair is not checked while one of its boxes is unusable", () => {
    const errors = FlowSettingsForm.errors(form({ band_fail_below: "", band_excellent_above: "20" }));

    expect(Object.keys(errors)).toEqual(["band_fail_below"]);
  });
});

describe("patch", () => {
  test("sends only what changed, as numbers", () => {
    expect(FlowSettingsForm.patch(saved, form({ retakes_per_day: "5", alignment_min_score: "4" }))).toEqual({ retakes_per_day: 5, alignment_min_score: 4 });
  });

  test("sends the switch and the lists when they changed", () => {
    const edited = form({ mastery_requires_all_correct: false, media_sources: ["wikimedia", "openverse", "giphy"], allowed_media_licenses: ["cc0"] });

    expect(FlowSettingsForm.patch(saved, edited)).toEqual({
      mastery_requires_all_correct: false,
      media_sources: ["wikimedia", "openverse", "giphy"],
      allowed_media_licenses: ["cc0"],
    });
  });

  test("is empty when nothing changed, including a list in another order", () => {
    expect(FlowSettingsForm.patch(saved, form())).toEqual({});
    expect(FlowSettingsForm.patch(saved, form({ media_sources: ["openverse", "wikimedia"] }))).toEqual({});
  });
});

describe("dirty", () => {
  test("names the fields that differ from what is saved", () => {
    expect(FlowSettingsForm.dirty(saved, form())).toEqual([]);
    expect(FlowSettingsForm.dirty(saved, form({ retakes_per_day: "4", media_sources: ["wikimedia"] }))).toEqual(["retakes_per_day", "media_sources"]);
  });

  test("an unusable box counts as unsaved (it differs), without being sent", () => {
    expect(FlowSettingsForm.dirty(saved, form({ retakes_per_day: "" }))).toEqual(["retakes_per_day"]);
    expect(FlowSettingsForm.patch(saved, form({ retakes_per_day: "" }))).toEqual({});
  });
});

describe("numbers", () => {
  test("uses the saved value where a box is unusable", () => {
    const numbers = FlowSettingsForm.numbers(saved, form({ diagnostic_questions_per_band: "", retakes_per_day: "5" }));

    expect(numbers.diagnostic_questions_per_band).toBe(2);
    expect(numbers.retakes_per_day).toBe(5);
  });
});

describe("toggle", () => {
  const options = ["a", "b", "c"];

  test("adds in the order of the options and removes", () => {
    expect(FlowSettingsForm.toggle(["a", "c"], "b", options)).toEqual(["a", "b", "c"]);
    expect(FlowSettingsForm.toggle(["a", "b", "c"], "b", options)).toEqual(["a", "c"]);
  });

  test("keeps a value the page does not list", () => {
    expect(FlowSettingsForm.toggle(["a", "legacy"], "b", options)).toEqual(["a", "b", "legacy"]);
    expect(FlowSettingsForm.toggle(["a", "legacy"], "a", options)).toEqual(["legacy"]);
  });
});

describe("serverErrors", () => {
  test("is the first message per field the API gave", () => {
    const error = new ApiError(400, "invalid", "x", { question_batch_size: ["Too big.", "Really."], media_sources: ["Unknown source."] });

    expect(FlowSettingsForm.serverErrors(error)).toEqual({ question_batch_size: "Too big.", media_sources: "Unknown source." });
  });

  test("is empty for a failure that is not about a field", () => {
    expect(FlowSettingsForm.serverErrors(new TypeError("offline"))).toEqual({});
    expect(FlowSettingsForm.serverErrors(new ApiError(429, "throttled", "x"))).toEqual({});
  });
});
