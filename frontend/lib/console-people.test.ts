/**
 * Unit under test: `lib/console-people.ts`, which turns the learners list into what the Learners page shows: row
 * words (studies, goal, language, last active, onboarding), the four tiles, the search in the address, and the link
 * to the Django admin.
 *
 * Why: this page is how staff see who uses Socra. A "most common" tile that follows the search box, an onboarding
 * percentage that divides by zero, a language shown as its code, or an admin link built from an unset or hostile
 * setting would each mislead or send someone somewhere wrong.
 *
 * Use cases:
 * - studies reads "School · Class 10" or just the level (a bare number is a class for school and a year for college), and a dash when nothing was filled in; goal and language are
 *   named like the learner chose them (a language in its own script); an unknown code is shown as it is
 * - last active is relative with the exact time for a hover, and "Never" for someone who has not come back
 * - the onboarding pill says Finished or Not finished, and a staff badge is only for staff
 * - the tiles: learners with those new this week (a lower bound when only part of the list is known), finished
 *   onboarding as a share of everyone, active this week, and the most common level and class
 * - the most common level and class counts only learners who gave one, ties go to the first alphabetically, and a
 *   partial sample says so
 * - an empty app shows dashes, not 0% or NaN
 * - the search is read from `?q=` trimmed and written only when there is something to search for
 * - the admin link is built from an http(s) address, whether the setting holds the origin or the admin's own address,
 *   and there is no link when it is unset or not a web address
 */
import { describe, expect, test } from "bun:test";

import { AdminLinks, LearnerStats, LearnerText, PeopleUrl } from "./console-people";
import type { ConsoleLearner, LearnerSummary } from "./types";

const NOW = new Date("2026-03-15T12:00:00Z");

function learner(patch: Partial<ConsoleLearner> = {}): ConsoleLearner {
  return {
    id: "u1",
    name: "Aditi Rao",
    email: "aditi@example.com",
    education_level: "school",
    grade_or_year: "Class 10",
    goal: "exam_prep",
    preferred_language: "hi",
    lessons_count: 6,
    last_active_at: "2026-03-15T11:48:00Z",
    profile_complete: true,
    is_staff: false,
    joined_at: "2026-03-01T08:00:00Z",
    ...patch,
  };
}

const summary: LearnerSummary = { total: 37, active_7d: 22, profile_complete: 31, staff: 2 };

describe("LearnerText", () => {
  test.each([
    [{ education_level: "school", grade_or_year: "Class 10" }, "School · Class 10"],
    [{ education_level: "undergraduate", grade_or_year: "2nd year" }, "College · 2nd year"],
    [{ education_level: "self_learner", grade_or_year: "" }, "Self-learner"],
    [{ education_level: "", grade_or_year: "" }, "–"],
    [{ education_level: "", grade_or_year: "Class 9" }, "Class 9"],
    [{ education_level: "school", grade_or_year: "10" }, "School · Class 10"],
    [{ education_level: "undergraduate", grade_or_year: "4" }, "College · Year 4"],
    [{ education_level: "postgraduate", grade_or_year: "1" }, "Postgraduate · Year 1"],
    [{ education_level: "professional", grade_or_year: "3" }, "Working · 3"],
    [{ education_level: "school", grade_or_year: "Grade 8" }, "School · Grade 8"],
  ] as const)("studies of %p reads %p", (patch, text) => {
    expect(LearnerText.studies(learner(patch))).toBe(text);
  });

  test("a learner without a name is shown as having none", () => {
    expect(LearnerText.displayName({ name: "Aditi" })).toBe("Aditi");
    expect(LearnerText.displayName({ name: "  " })).toBe("No name");
  });

  test("goal and language use the learner's own wording, an unknown code stays as it is", () => {
    expect(LearnerText.goal(learner({ goal: "interview_prep" }))).toBe("Interview prep");
    expect(LearnerText.goal(learner({ goal: "" }))).toBe("–");
    expect(LearnerText.language("hi")).toBe("हिन्दी");
    expect(LearnerText.language("en")).toBe("English");
    expect(LearnerText.language("xx")).toBe("xx");
    expect(LearnerText.language("")).toBe("–");
  });

  test("last active is relative, with the exact time for a hover, and Never when there is none", () => {
    expect(LearnerText.lastActive("2026-03-15T11:48:00Z", NOW)).toEqual({ text: "12 min ago", title: expect.stringContaining("2026") });
    expect(LearnerText.lastActive(null, NOW)).toEqual({ text: "Never", title: "Has not signed in or opened a lesson" });
  });

  test("onboarding is finished or not", () => {
    expect(LearnerText.onboarding(learner())).toEqual({ label: "Finished", tone: "ok" });
    expect(LearnerText.onboarding(learner({ profile_complete: false }))).toEqual({ label: "Not finished", tone: "off" });
  });
});

describe("LearnerStats.mostCommon", () => {
  test("counts level and class together, only for learners who gave a level", () => {
    const rows = [
      learner({ id: "1" }),
      learner({ id: "2" }),
      learner({ id: "3", education_level: "undergraduate", grade_or_year: "2nd year" }),
      learner({ id: "4", education_level: "", grade_or_year: "" }),
    ];

    expect(LearnerStats.mostCommon(rows)).toEqual({ label: "School · Class 10", count: 2 });
  });

  test("a tie goes to the first alphabetically, and nobody with a level gives nothing", () => {
    const tie = [learner({ id: "1", education_level: "school", grade_or_year: "Class 9" }), learner({ id: "2", education_level: "school", grade_or_year: "Class 10" })];

    expect(LearnerStats.mostCommon(tie)?.label).toBe("School · Class 10");
    expect(LearnerStats.mostCommon([learner({ education_level: "" })])).toBeNull();
    expect(LearnerStats.mostCommon([])).toBeNull();
  });
});

describe("LearnerStats.newThisWeek", () => {
  const recent = (id: string) => learner({ id, joined_at: "2026-03-13T10:00:00Z" });
  const old = (id: string) => learner({ id, joined_at: "2026-02-01T10:00:00Z" });

  test("counts those who joined in the last 7 days", () => {
    expect(LearnerStats.newThisWeek([recent("1"), recent("2"), old("3")], false, NOW)).toEqual({ count: 2, atLeast: false });
  });

  test("is a lower bound when every known learner is new and there are more", () => {
    expect(LearnerStats.newThisWeek([recent("1"), recent("2")], true, NOW)).toEqual({ count: 2, atLeast: true });
    expect(LearnerStats.newThisWeek([recent("1"), old("2")], true, NOW)).toEqual({ count: 1, atLeast: false });
  });
});

describe("LearnerStats.tiles", () => {
  test("four tiles: learners, finished onboarding, active this week, most common", () => {
    const sample = [learner({ id: "1", joined_at: "2026-03-14T10:00:00Z" }), learner({ id: "2", joined_at: "2026-02-01T10:00:00Z" })];
    const tiles = LearnerStats.tiles(summary, { rows: sample, more: false }, NOW);

    expect(tiles.map((t) => [t.key, t.label, t.value, t.detail])).toEqual([
      ["learners", "Learners", "37", "+1 this week"],
      ["onboarding", "Finished onboarding", "84%", "31 of 37 learners"],
      ["active", "Active this week", "22", "Signed in or opened a lesson"],
      ["common", "Most common", "School · Class 10", "2 learners"],
    ]);
  });

  test("says when the sample is only the newest learners", () => {
    const rows = [learner({ id: "1", joined_at: "2026-03-14T10:00:00Z" })];
    const tiles = LearnerStats.tiles(summary, { rows, more: true }, NOW);

    expect(tiles[0]!.detail).toBe("+1 or more this week");
    expect(tiles[3]!.detail).toBe("1 of the newest 1");
  });

  test("nobody new, nobody yet, and nobody with a profile are said plainly", () => {
    const empty = LearnerStats.tiles({ total: 0, active_7d: 0, profile_complete: 0, staff: 0 }, { rows: [], more: false }, NOW);

    expect(empty.map((t) => t.value)).toEqual(["0", "–", "0", "–"]);
    expect(empty[0]!.detail).toBe("None joined this week");
    expect(empty[3]!.detail).toBe("No one has chosen a level yet");
  });
});

describe("PeopleUrl search", () => {
  test("is read trimmed and written only when there is text", () => {
    expect(PeopleUrl.search(new URLSearchParams("q=%20aditi%20"))).toBe("aditi");
    expect(PeopleUrl.search(new URLSearchParams(""))).toBe("");
    expect(PeopleUrl.searchQuery("aditi rao")).toBe("?q=aditi+rao");
    expect(PeopleUrl.searchQuery("   ")).toBe("");
  });
});

describe("AdminLinks.userChange", () => {
  test("uses the admin's address as given, or adds /admin to an origin", () => {
    expect(AdminLinks.userChange("http://localhost:7010/admin", "u-1")).toBe("http://localhost:7010/admin/accounts/user/u-1/change/");
    expect(AdminLinks.userChange("http://localhost:7010/admin/", "u-1")).toBe("http://localhost:7010/admin/accounts/user/u-1/change/");
    expect(AdminLinks.userChange("https://api.socra.example", "u-1")).toBe("https://api.socra.example/admin/accounts/user/u-1/change/");
  });

  test("has no link when the setting is missing or is not a web address", () => {
    expect(AdminLinks.userChange(undefined, "u-1")).toBeNull();
    expect(AdminLinks.userChange("", "u-1")).toBeNull();
    expect(AdminLinks.userChange("javascript:alert(1)", "u-1")).toBeNull();
    expect(AdminLinks.userChange("not a url", "u-1")).toBeNull();
  });

  test("an id cannot change the path", () => {
    expect(AdminLinks.userChange("http://h/admin", "a/../b?c")).toBe("http://h/admin/accounts/user/a%2F..%2Fb%3Fc/change/");
  });
});
