/**
 * Unit under test: `BrowserTimezone`, everything the sign-up form and the profile page know about a time zone.
 *
 * Why: the learner's day (the daily credit, the streak) is the day in their zone. The browser knows the zone, so sign-up
 * sends it; the profile lets the learner correct it, but only once every 30 days, and has to say so plainly. The server
 * is the authority on all of it. This class only saves the learner a refused request and finds names in a long list.
 *
 * Use cases:
 * - the browser's zone is read when the engine can say it, and is null when it cannot or says something blank
 * - the zone shown on the profile is the saved one, else the browser's, else Asia/Kolkata
 * - the list offered is the engine's list with the saved and detected zones always in it, sorted, with no repeats; an
 *   engine that cannot list zones still offers those and Asia/Kolkata
 * - a search ignores case, spaces, slashes, dashes and underscores, puts names where a word starts with the search before
 *   names that only contain it, and an empty search gives the whole list
 * - a name is valid only when it is in the list
 * - the lock: open when the server says none or the date has passed; shut before; the note names the date in the
 *   learner's own zone, and there is no note when it is open
 * - a save sends the zone only when it changed or none was saved yet
 */
import { describe, expect, test } from "bun:test";

import { BrowserTimezone } from "./browser-timezone";

describe("detect", () => {
  test("the browser's zone", () => {
    expect(BrowserTimezone.detect(() => "Europe/London")).toBe("Europe/London");
  });

  test.each([undefined, "", "   "])("%p is no zone", (value) => {
    expect(BrowserTimezone.detect(() => value as string | undefined)).toBeNull();
  });

  test("an engine that throws is no zone", () => {
    expect(
      BrowserTimezone.detect(() => {
        throw new Error("no Intl");
      }),
    ).toBeNull();
  });
});

describe("initial", () => {
  test("the saved zone wins", () => {
    expect(BrowserTimezone.initial("Europe/London", "America/New_York")).toBe("Europe/London");
  });

  test("with none saved, the browser's", () => {
    expect(BrowserTimezone.initial("", "America/New_York")).toBe("America/New_York");
  });

  test("with neither, India's", () => {
    expect(BrowserTimezone.initial("", null)).toBe("Asia/Kolkata");
    expect(BrowserTimezone.DEFAULT).toBe("Asia/Kolkata");
  });
});

describe("names", () => {
  test("the engine's list, sorted, with the saved and detected zones included once", () => {
    const names = BrowserTimezone.names(() => ["Europe/London", "Asia/Tokyo", "Europe/London"], "Asia/Calcutta", "Asia/Kolkata");

    expect(names).toEqual(["Asia/Calcutta", "Asia/Kolkata", "Asia/Tokyo", "Europe/London"]);
  });

  test("an engine that cannot list zones still offers the ones we know", () => {
    expect(BrowserTimezone.names(null, "", "Europe/London")).toEqual(["Asia/Kolkata", "Europe/London"]);
    expect(
      BrowserTimezone.names(() => {
        throw new Error("unsupported");
      }, "", null),
    ).toEqual(["Asia/Kolkata"]);
  });

  test("a blank saved or detected zone adds nothing", () => {
    expect(BrowserTimezone.names(() => ["Asia/Tokyo"], "", null)).toEqual(["Asia/Tokyo"]);
  });
});

describe("search", () => {
  const names = ["America/New_York", "Asia/Kolkata", "Asia/Kathmandu", "Europe/London", "America/North_Dakota/Center"];

  test("an empty search is the whole list", () => {
    expect(BrowserTimezone.search(names, "  ")).toEqual(names);
  });

  test("case, spaces, slashes and underscores do not matter", () => {
    expect(BrowserTimezone.search(names, "new york")).toEqual(["America/New_York"]);
    expect(BrowserTimezone.search(names, "NEW_YORK")).toEqual(["America/New_York"]);
    expect(BrowserTimezone.search(names, "asia/kol")).toEqual(["Asia/Kolkata"]);
  });

  test("a name where a word starts with the search comes before one that only contains it", () => {
    expect(BrowserTimezone.search(["America/New_York", "Europe/Orkney"], "ork")).toEqual(["Europe/Orkney", "America/New_York"]);
    expect(BrowserTimezone.search(["Pacific/Kolkata_Island", "Asia/Kolkata", "Kolkata/Town"], "kolkata")).toEqual(["Pacific/Kolkata_Island", "Asia/Kolkata", "Kolkata/Town"]);
  });

  test("nothing matches nothing", () => {
    expect(BrowserTimezone.search(names, "mars")).toEqual([]);
  });
});

describe("isValid", () => {
  test("only a name in the list is", () => {
    const names = ["Asia/Kolkata", "Europe/London"];

    expect(BrowserTimezone.isValid("Europe/London", names)).toBe(true);
    expect(BrowserTimezone.isValid("europe/london", names)).toBe(false);
    expect(BrowserTimezone.isValid("", names)).toBe(false);
    expect(BrowserTimezone.isValid("Mars/Olympus", names)).toBe(false);
  });
});

describe("the 30-day lock", () => {
  const NOW = new Date("2026-11-05T12:00:00Z");

  test.each([null, "2026-11-05T12:00:00Z", "2026-10-01T00:00:00Z"])("%p is open", (until) => {
    expect(BrowserTimezone.isLocked(until, NOW)).toBe(false);
    expect(BrowserTimezone.lockNote(until, NOW, "Asia/Kolkata")).toBeNull();
  });

  test("a date in the future is shut, and the note names it in the learner's zone", () => {
    expect(BrowserTimezone.isLocked("2026-12-04T20:00:00Z", NOW)).toBe(true);
    // 20:00Z is 01:30 the next morning in India
    expect(BrowserTimezone.lockNote("2026-12-04T20:00:00Z", NOW, "Asia/Kolkata")).toBe("You can change your time zone again on 5 December 2026.");
    expect(BrowserTimezone.lockNote("2026-12-04T20:00:00Z", NOW, "America/New_York")).toBe("You can change your time zone again on 4 December 2026.");
  });

  test("an unreadable date is treated as open rather than locking the learner out", () => {
    expect(BrowserTimezone.isLocked("soon", NOW)).toBe(false);
    expect(BrowserTimezone.lockNote("soon", NOW, "Asia/Kolkata")).toBeNull();
  });

  test("the standing note says what the rule is", () => {
    expect(BrowserTimezone.RULE).toBe("You can change this once every 30 days.");
    expect(BrowserTimezone.LOCK_DAYS).toBe(30);
  });
});

describe("what a save sends", () => {
  test("nothing when the zone is the saved one", () => {
    expect(BrowserTimezone.payload("Europe/London", "Europe/London")).toEqual({});
  });

  test("the zone when it changed", () => {
    expect(BrowserTimezone.payload("Asia/Tokyo", "Europe/London")).toEqual({ timezone: "Asia/Tokyo" });
  });

  test("the zone when none was saved yet, so the first save keeps what the browser said", () => {
    expect(BrowserTimezone.payload("Asia/Kolkata", "")).toEqual({ timezone: "Asia/Kolkata" });
  });

  test("nothing for a blank choice", () => {
    expect(BrowserTimezone.payload("  ", "Europe/London")).toEqual({});
  });
});

describe("a refusal from the server", () => {
  test("the locked answer becomes a sentence with the date", () => {
    expect(BrowserTimezone.lockedMessage("2026-12-04T20:00:00Z", "Asia/Kolkata")).toBe("You can change your time zone again on 5 December 2026.");
  });

  test("without a date it still says something kind", () => {
    expect(BrowserTimezone.lockedMessage(undefined, "Asia/Kolkata")).toBe("You changed your time zone recently. Try again in a few weeks.");
  });
});
