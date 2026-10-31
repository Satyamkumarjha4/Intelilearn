/**
 * Unit under test: `SheetCatalog`, `SheetTabs`, `SheetRequests` and `MasteryBanner`, what a lesson says about its study
 * sheets.
 *
 * Why: the choice screen and the Study sheets tab are built from one description of the three sheets, so their names,
 * button labels and reading times cannot drift apart. The tab row has to tell a sheet that exists from one that can be
 * added and one being written right now, and the API lists a lesson's sheets in alphabetical order, so the row must
 * not depend on that order. The banner is the first thing a learner reads after acing the quick check.
 *
 * Use cases:
 * - there are three sheets, always cheat, revision, practice; each has a title, a one-line description, three
 *   bullets and a rough reading time
 * - the choice button and the "add" tab are worded after the sheet ("Make my revision sheet", "Add practice sheet")
 * - the tab row lists the sheets a lesson has first, in the catalogue's order whatever order the API gave, then one
 *   "missing" tab for each sheet it can be asked for and lacks; a practice sheet that exists is listed, but a missing
 *   one is never offered
 * - sheets being written show as "building" among the others, and a sheet that already exists is never "building"
 * - the sheets that can still be asked for are the cheat sheet and the revision sheet the lesson lacks; both can be
 *   asked for together only when it has neither; what to send is one kind or the pair
 * - an "already exists" answer names the sheets that exist, so the page opens one instead of asking again; any other
 *   error names none
 * - the open tab is the one asked for if it exists or is being written; otherwise the first sheet there is, and null
 *   when the lesson has none yet
 * - a perfect score reads "10 out of 10. You already know this!", a near-perfect one says "well", and a missing
 *   result still congratulates
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { MasteryBanner, SheetCatalog, SheetRequests, SheetTabs } from "./study-sheets";

describe("SheetCatalog", () => {
  test("lists the three sheets in the order a learner reads them", () => {
    expect(SheetCatalog.all().map((s) => s.kind)).toEqual(["cheat_sheet", "revision_sheet", "practice_sheet"]);
  });

  test.each(SheetCatalog.all())("the $kind has a title, a description, three bullets and a reading time", (sheet) => {
    expect(sheet.title.length).toBeGreaterThan(0);
    expect(sheet.text.length).toBeGreaterThan(0);
    expect(sheet.bullets).toHaveLength(3);
    expect(sheet.time.length).toBeGreaterThan(0);
  });

  test("a sheet is found by its kind", () => {
    expect(SheetCatalog.of("revision_sheet").title).toBe("Revision sheet");
  });

  test("the choice button and the add tab are worded after the sheet", () => {
    expect(SheetCatalog.makeLabel("revision_sheet")).toBe("Make my revision sheet");
    expect(SheetCatalog.addLabel("practice_sheet")).toBe("Add practice sheet");
  });

  test("a sheet is named in a sentence in lower case", () => {
    expect(SheetCatalog.noun("cheat_sheet")).toBe("cheat sheet");
  });
});

describe("SheetTabs.of", () => {
  test("a lesson with no sheets offers the two that can be asked for", () => {
    expect(SheetTabs.of([], []).map((t) => [t.kind, t.state])).toEqual([
      ["cheat_sheet", "missing"],
      ["revision_sheet", "missing"],
    ]);
  });

  test("the sheets it has come first in the catalogue's order, whatever order the API listed them in", () => {
    const tabs = SheetTabs.of(["practice_sheet", "cheat_sheet"], []);
    expect(tabs.map((t) => [t.kind, t.state])).toEqual([
      ["cheat_sheet", "ready"],
      ["practice_sheet", "ready"],
      ["revision_sheet", "missing"],
    ]);
  });

  test("a practice sheet is shown only when it exists, and never offered to add", () => {
    expect(SheetTabs.of([], []).some((t) => t.kind === "practice_sheet")).toBe(false);
    expect(SheetTabs.of(["practice_sheet"], ["practice_sheet"]).find((t) => t.kind === "practice_sheet")?.state).toBe("ready");
  });

  test("sheets being written are shown as building among those still to add", () => {
    const tabs = SheetTabs.of(["cheat_sheet"], ["revision_sheet"]);
    expect(tabs.map((t) => [t.kind, t.state])).toEqual([
      ["cheat_sheet", "ready"],
      ["revision_sheet", "building"],
    ]);
    expect(SheetTabs.of([], ["cheat_sheet", "revision_sheet"]).map((t) => t.state)).toEqual(["building", "building"]);
  });

  test("a sheet that already exists is ready even if it is also named as being written", () => {
    expect(SheetTabs.of(["cheat_sheet"], ["cheat_sheet"])[0].state).toBe("ready");
  });

  test("every tab carries the sheet's title", () => {
    expect(SheetTabs.of([], []).map((t) => t.title)).toEqual(["Cheat sheet", "Revision sheet"]);
  });
});

describe("SheetTabs.pick", () => {
  const tabs = SheetTabs.of(["cheat_sheet"], ["revision_sheet"]);

  test("opens the sheet asked for when it exists", () => {
    expect(SheetTabs.pick(SheetTabs.of(["cheat_sheet", "revision_sheet"], []), "revision_sheet")).toBe("revision_sheet");
  });

  test("opens a sheet that is being written, so its progress shows in its own tab", () => {
    expect(SheetTabs.pick(tabs, "revision_sheet")).toBe("revision_sheet");
  });

  test("falls back to the first sheet when none is asked for", () => {
    expect(SheetTabs.pick(tabs, null)).toBe("cheat_sheet");
  });

  test("falls back to the first sheet when the one asked for can only be added", () => {
    expect(SheetTabs.pick(SheetTabs.of(["cheat_sheet"], []), "revision_sheet")).toBe("cheat_sheet");
  });

  test("is null when the lesson has no sheet and none is being written", () => {
    expect(SheetTabs.pick(SheetTabs.of([], []), null)).toBeNull();
  });
});

describe("SheetRequests", () => {
  test.each([
    [[], ["cheat_sheet", "revision_sheet"]],
    [["cheat_sheet"], ["revision_sheet"]],
    [["revision_sheet"], ["cheat_sheet"]],
    [["revision_sheet", "cheat_sheet"], []],
    [["practice_sheet"], ["cheat_sheet", "revision_sheet"]],
  ] as const)("a lesson that has %j can be asked for %j", (have, missing) => {
    expect(SheetRequests.missing([...have])).toEqual([...missing]);
  });

  test("both can be asked for together only when the lesson has neither", () => {
    expect(SheetRequests.canAskForBoth([])).toBe(true);
    expect(SheetRequests.canAskForBoth(["practice_sheet"])).toBe(true);
    expect(SheetRequests.canAskForBoth(["cheat_sheet"])).toBe(false);
    expect(SheetRequests.canAskForBoth(["cheat_sheet", "revision_sheet"])).toBe(false);
  });

  test("what an add tab asks for: its own sheet, or the pair", () => {
    expect(SheetRequests.one("revision_sheet")).toEqual(["revision_sheet"]);
    expect(SheetRequests.pair()).toEqual(["cheat_sheet", "revision_sheet"]);
  });

  test("the add words for both", () => {
    expect(SheetRequests.bothLabel()).toBe("Add both sheets");
  });

  test("an already exists answer names the sheets that exist, and only the ones that are sheets", () => {
    const exists = new ApiError(409, "already_exists", "x", {}, { kinds: ["revision_sheet", "poster"] });

    expect(SheetRequests.existing(exists)).toEqual(["revision_sheet"]);
  });

  test.each([
    new ApiError(409, "wrong_stage", "x", {}, { kinds: ["cheat_sheet"] }),
    new ApiError(409, "already_exists", "x"),
    new ApiError(409, "already_exists", "x", {}, { kinds: "cheat_sheet" }),
    new Error("boom"),
    undefined,
  ])("%p names none", (error) => {
    expect(SheetRequests.existing(error)).toEqual([]);
  });
});

describe("MasteryBanner.of", () => {
  test("a perfect score is celebrated with the score in words", () => {
    expect(MasteryBanner.of({ correct: 10, total: 10 })).toEqual({
      headline: "10 out of 10. You already know this!",
      text: "No need for a full lesson. Pick a sheet to keep it sharp.",
    });
  });

  test("a score that is not perfect still passed, and says so gently", () => {
    expect(MasteryBanner.of({ correct: 9, total: 10 }).headline).toBe("9 out of 10. You already know this well!");
  });

  test("without a result the banner congratulates without a number", () => {
    expect(MasteryBanner.of(null).headline).toBe("You already know this!");
  });
});
