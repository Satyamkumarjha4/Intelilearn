/**
 * Unit under test: `SheetCatalog`, `SheetTabs` and `MasteryBanner`, what a mastery lesson says about its study sheets.
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
 *   "missing" tab for each sheet it lacks
 * - a sheet being written shows as "building" among the others, and a sheet that already exists is never "building"
 * - the open tab is the one asked for if it exists or is being written; otherwise the first sheet there is, and null
 *   when the lesson has none yet
 * - a perfect score reads "10 out of 10. You already know this!", a near-perfect one says "well", and a missing
 *   result still congratulates
 */
import { describe, expect, test } from "bun:test";

import { MasteryBanner, SheetCatalog, SheetTabs } from "./study-sheets";

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
  test("a lesson with no sheets offers all three to add", () => {
    expect(SheetTabs.of([], null).map((t) => [t.kind, t.state])).toEqual([
      ["cheat_sheet", "missing"],
      ["revision_sheet", "missing"],
      ["practice_sheet", "missing"],
    ]);
  });

  test("the sheets it has come first in the catalogue's order, whatever order the API listed them in", () => {
    const tabs = SheetTabs.of(["practice_sheet", "cheat_sheet"], null);
    expect(tabs.map((t) => [t.kind, t.state])).toEqual([
      ["cheat_sheet", "ready"],
      ["practice_sheet", "ready"],
      ["revision_sheet", "missing"],
    ]);
  });

  test("a sheet being written is shown as building among those still to add", () => {
    const tabs = SheetTabs.of(["cheat_sheet"], "practice_sheet");
    expect(tabs.map((t) => [t.kind, t.state])).toEqual([
      ["cheat_sheet", "ready"],
      ["revision_sheet", "missing"],
      ["practice_sheet", "building"],
    ]);
  });

  test("a sheet that already exists is ready even if it is also named as being written", () => {
    expect(SheetTabs.of(["cheat_sheet"], "cheat_sheet")[0].state).toBe("ready");
  });

  test("every tab carries the sheet's title", () => {
    expect(SheetTabs.of([], null).map((t) => t.title)).toEqual(["Cheat sheet", "Revision sheet", "Practice sheet"]);
  });
});

describe("SheetTabs.pick", () => {
  const tabs = SheetTabs.of(["cheat_sheet", "revision_sheet"], "practice_sheet");

  test("opens the sheet asked for when it exists", () => {
    expect(SheetTabs.pick(tabs, "revision_sheet")).toBe("revision_sheet");
  });

  test("opens a sheet that is being written, so its progress shows in its own tab", () => {
    expect(SheetTabs.pick(tabs, "practice_sheet")).toBe("practice_sheet");
  });

  test("falls back to the first sheet when none is asked for", () => {
    expect(SheetTabs.pick(tabs, null)).toBe("cheat_sheet");
  });

  test("falls back to the first sheet when the one asked for can only be added", () => {
    expect(SheetTabs.pick(SheetTabs.of(["cheat_sheet"], null), "practice_sheet")).toBe("cheat_sheet");
  });

  test("is null when the lesson has no sheet and none is being written", () => {
    expect(SheetTabs.pick(SheetTabs.of([], null), null)).toBeNull();
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
