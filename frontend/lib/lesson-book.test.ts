/**
 * Unit under test: `LessonBook`, `ReadPages` and `BookKeys`, the state of the lesson notebook around the lesson iframe.
 *
 * Why: the book is how a learner moves through the lesson. A page counter that disagrees with the page, a "next" that
 * walks off the end, ticks that vanish (or crash the page) when the browser has no storage, or arrow keys that turn
 * the page while someone types an answer would each make a working lesson feel broken.
 *
 * Use cases:
 * - the eyebrow, title and footer say which page of how many, naming the usual three pages (Introduction, Core,
 *   Advanced) and falling back to "Page n"; the title is the page's own title when the document sent one
 * - moving goes to a page, never past either end, and the page left behind counts as read
 * - the flaps are one per page, tinted primary, marigold, insight in turn, with the open one active and the read ones
 *   ticked (the open page is not ticked)
 * - new pages from the document keep the place when it still exists and clamp it when it does not
 * - the next button is "Next page" until the last page; there it goes to the test, or to the test results once the
 *   test was submitted; finishing the last page counts it as read
 * - read pages are kept per lesson in storage, survive a reload, and the book works when storage is missing, full,
 *   or holds rubbish
 * - pages read in an earlier visit join the ones read now (those past the end are ignored once the count is known)
 * - the arrow keys turn pages unless a modifier is held, someone is typing, or a dialog or menu is open
 */
import { describe, expect, test } from "bun:test";

import { BookKeys, LessonBook, ReadPages } from "./lesson-book";

const three = () => new LessonBook(3, ["Why searching matters", "How halving works", "Edge cases"]);

describe("labels", () => {
  test("say which page of how many, with the page's usual name", () => {
    const book = three().goTo(1);

    expect(book.eyebrow).toBe("Page 2 of 3 · Core");
    expect(book.footer).toBe("Page 2 of 3");
    expect(book.title).toBe("How halving works");
  });

  test.each([
    [0, "Introduction"],
    [1, "Core"],
    [2, "Advanced"],
  ])("page %i is %s", (index, name) => {
    expect(three().goTo(index).name).toBe(name);
  });

  test("a book without titles uses the name, and one with another number of pages says Page n", () => {
    expect(new LessonBook(3).title).toBe("Introduction");
    expect(new LessonBook(5).goTo(3).eyebrow).toBe("Page 4 of 5 · Page 4");
  });

  test("a book that has not heard from the document yet has nothing to say", () => {
    const book = new LessonBook(0);

    expect(book.eyebrow).toBe("Opening your lesson…");
    expect(book.flaps).toEqual([]);
    expect(book.isFirst && book.isLast).toBe(true);
  });
});

describe("moving", () => {
  test("goes to a page and never past either end", () => {
    const book = three();

    expect(book.next().index).toBe(1);
    expect(book.prev().index).toBe(0);
    expect(book.goTo(9).index).toBe(2);
    expect(book.goTo(-4).index).toBe(0);
    expect(book.goTo(2).next().index).toBe(2);
  });

  test("the page left behind counts as read, and standing still reads nothing", () => {
    const book = three().next().next();

    expect([...book.read].sort()).toEqual([0, 1]);
    expect(three().goTo(0).read.size).toBe(0);
    expect(book.isFirst).toBe(false);
    expect(book.isLast).toBe(true);
  });

  test("it does not change the book it started from", () => {
    const book = three();
    book.next();

    expect(book.index).toBe(0);
    expect(book.read.size).toBe(0);
  });
});

describe("pages read before", () => {
  test("join the ones read now, and the ones past the end are ignored", () => {
    const book = three().next().withRead(new Set([2, 7]));

    expect([...book.read].sort()).toEqual([0, 2]);
  });

  test("are kept while the document has not said how many pages it has", () => {
    expect([...new LessonBook(0).withRead(new Set([1, 2])).read].sort()).toEqual([1, 2]);
  });
});

describe("flaps", () => {
  test("one per page, tinted in turn, the open one active, read ones ticked", () => {
    const book = new LessonBook(3, [], 1, new Set([0, 1]));

    expect(book.flaps).toEqual([
      { index: 0, label: "Introduction", tone: "primary", active: false, read: true },
      { index: 1, label: "Core", tone: "marigold", active: true, read: false },
      { index: 2, label: "Advanced", tone: "insight", active: false, read: false },
    ]);
  });

  test("the tints start again after the third page", () => {
    expect(new LessonBook(4).flaps.map((f) => f.tone)).toEqual(["primary", "marigold", "insight", "primary"]);
  });
});

describe("new pages from the document", () => {
  test("keep the place and the ticks when the page still exists", () => {
    const book = three().next().withPages(3, ["a", "b", "c"]);

    expect([book.index, book.title, [...book.read]]).toEqual([1, "b", [0]]);
  });

  test("clamp the place when the document has fewer pages, and drop ticks for pages that are gone", () => {
    const book = new LessonBook(3, [], 2, new Set([0, 1])).withPages(2, []);

    expect([book.index, [...book.read].sort()]).toEqual([1, [0, 1]]);
    expect(new LessonBook(3, [], 2, new Set([2])).withPages(2, []).read.size).toBe(0);
  });
});

describe("the next button", () => {
  test("is Next page until the last page", () => {
    expect(three().nextAction("not_started")).toEqual({ kind: "page", label: "Next page →" });
  });

  test.each([
    ["not_started", "Go to the test →"],
    ["grading", "See your test results →"],
    ["graded", "See your test results →"],
    ["failed", "See your test results →"],
  ] as const)("on the last page goes to the test: test %s says %s", (status, label) => {
    expect(three().goTo(2).nextAction(status)).toEqual({ kind: "test", label });
  });

  test("finishing the last page counts it as read", () => {
    expect([...three().goTo(2).finish().read].sort()).toEqual([0, 2]);
    expect(three().goTo(2).finish().flaps[2].read).toBe(false); // the open page is never ticked
    expect(three().goTo(2).finish().goTo(0).flaps[2].read).toBe(true);
  });
});

describe("ReadPages", () => {
  const store = (initial: Record<string, string> = {}) => {
    const data = { ...initial };
    return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
  };

  test("keeps the read pages per lesson and reads them back", () => {
    const storage = store();
    new ReadPages("L1", storage).save(new Set([0, 2]));

    expect([...new ReadPages("L1", storage).load()]).toEqual([0, 2]);
    expect(new ReadPages("L2", storage).load().size).toBe(0);
  });

  test.each([["not json"], ['{"a":1}'], ["[1,-2,\"x\",null,2.5,3]"]])("%s is read as far as it makes sense", (raw) => {
    const loaded = new ReadPages("L1", store({ "lesson-book:read:L1": raw })).load();

    expect([...loaded].every((n) => Number.isInteger(n) && n >= 0)).toBe(true);
  });

  test("works without storage, and when storage throws", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("full");
      },
    };

    expect(new ReadPages("L1", null).load().size).toBe(0);
    expect(() => new ReadPages("L1", null).save(new Set([1]))).not.toThrow();
    expect(new ReadPages("L1", broken).load().size).toBe(0);
    expect(() => new ReadPages("L1", broken).save(new Set([1]))).not.toThrow();
  });
});

describe("BookKeys.direction", () => {
  const press = (key: string, over = {}) => ({ key, target: { tagName: "BODY", isContentEditable: false }, ...over });

  test("turns pages with the arrow keys", () => {
    expect(BookKeys.direction(press("ArrowRight"))).toBe(1);
    expect(BookKeys.direction(press("ArrowLeft"))).toBe(-1);
    expect(BookKeys.direction(press("ArrowUp"))).toBe(0);
    expect(BookKeys.direction(press("a"))).toBe(0);
  });

  test.each([["altKey"], ["ctrlKey"], ["metaKey"], ["shiftKey"]])("does nothing while %s is held", (modifier) => {
    expect(BookKeys.direction(press("ArrowRight", { [modifier]: true }))).toBe(0);
  });

  test.each([["INPUT"], ["TEXTAREA"], ["SELECT"]])("does nothing while someone is in a %s", (tagName) => {
    expect(BookKeys.direction(press("ArrowRight", { target: { tagName, isContentEditable: false } }))).toBe(0);
  });

  test("does nothing in editable text or a slider-like control, and copes with no target", () => {
    expect(BookKeys.direction(press("ArrowRight", { target: { tagName: "DIV", isContentEditable: true } }))).toBe(0);
    expect(BookKeys.direction(press("ArrowRight", { target: { tagName: "DIV", isContentEditable: false, getAttribute: () => "slider" } }))).toBe(0);
    expect(BookKeys.direction({ key: "ArrowRight", target: null })).toBe(1);
  });

  test("does nothing inside a dialog or a menu", () => {
    const inside = { tagName: "BUTTON", isContentEditable: false, closest: () => ({}) };
    const outside = { tagName: "BUTTON", isContentEditable: false, closest: () => null };

    expect(BookKeys.direction({ key: "ArrowRight", target: inside })).toBe(0);
    expect(BookKeys.direction({ key: "ArrowRight", target: outside })).toBe(1);
  });
});
