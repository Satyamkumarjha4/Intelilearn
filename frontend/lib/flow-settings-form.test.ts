/**
 * Unit under test: `FlowSettingsForm`, the Lesson settings page's form: text boxes in, a validated patch out.
 *
 * Why: a number box holds text while someone types ("", "1e3", "2.5"), and the page must check it, show what is wrong
 * next to the box, and send only what changed. The API rejects values the admin would reject; checking them here as
 * well saves a round trip, and catches two settings that contradict each other (a minimum test length above the
 * maximum, a cut-off above the number of questions) that the API does not yet check.
 *
 * Use cases:
 * - turns the saved settings into form text and back
 * - checks each number against its range and says what is wrong in plain words
 * - checks pairs of settings against each other (test minimum and maximum, cut-off and questions)
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
  final_test_min: 10,
  final_test_max: 15,
  max_interactives_per_page: 3,
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
    expect(values.final_test_max).toBe("15");
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
    ["final_test_min", "0", "Enter a number from 1 to 32767."],
    ["alignment_max_rounds", "-1", "Enter a whole number."],
    ["alignment_max_rounds", "40000", "Enter a number from 0 to 32767."],
  ])("%s = %j: %s", (field, text, message) => {
    expect(FlowSettingsForm.errors(form({ [field]: text }))[field as keyof FlowSettingsValues]).toBe(message);
  });

  test("spaces around a number are fine", () => {
    expect(FlowSettingsForm.errors(form({ final_test_min: " 12 " }))).toEqual({});
  });

  test("a test minimum above the maximum is called out on the maximum", () => {
    expect(FlowSettingsForm.errors(form({ final_test_min: "20" })).final_test_max).toBe("Must be at least the minimum (20).");
    expect(FlowSettingsForm.errors(form({ final_test_min: "15" }))).toEqual({});
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
    const errors = FlowSettingsForm.errors(form({ final_test_min: "", final_test_max: "5" }));

    expect(Object.keys(errors)).toEqual(["final_test_min"]);
  });
});

describe("patch", () => {
  test("sends only what changed, as numbers", () => {
    expect(FlowSettingsForm.patch(saved, form({ final_test_max: "20", alignment_min_score: "4" }))).toEqual({ final_test_max: 20, alignment_min_score: 4 });
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
    expect(FlowSettingsForm.dirty(saved, form({ final_test_min: "11", media_sources: ["wikimedia"] }))).toEqual(["final_test_min", "media_sources"]);
  });

  test("an unusable box counts as unsaved (it differs), without being sent", () => {
    expect(FlowSettingsForm.dirty(saved, form({ final_test_min: "" }))).toEqual(["final_test_min"]);
    expect(FlowSettingsForm.patch(saved, form({ final_test_min: "" }))).toEqual({});
  });
});

describe("numbers", () => {
  test("uses the saved value where a box is unusable", () => {
    const numbers = FlowSettingsForm.numbers(saved, form({ diagnostic_questions_per_band: "", final_test_max: "20" }));

    expect(numbers.diagnostic_questions_per_band).toBe(2);
    expect(numbers.final_test_max).toBe(20);
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
    const error = new ApiError(400, "invalid", "x", { final_test_max: ["Too big.", "Really."], media_sources: ["Unknown source."] });

    expect(FlowSettingsForm.serverErrors(error)).toEqual({ final_test_max: "Too big.", media_sources: "Unknown source." });
  });

  test("is empty for a failure that is not about a field", () => {
    expect(FlowSettingsForm.serverErrors(new TypeError("offline"))).toEqual({});
    expect(FlowSettingsForm.serverErrors(new ApiError(429, "throttled", "x"))).toEqual({});
  });
});
