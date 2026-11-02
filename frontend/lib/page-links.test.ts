import { describe, expect, test } from "bun:test";

import { PageLinks } from "./page-links";

describe("PageLinks.indexOf", () => {
  test.each([
    ["introduction", 0],
    ["core", 1],
    ["advanced", 2],
  ] as const)("the %s page is book page %d", (key, index) => {
    expect(PageLinks.indexOf(key)).toBe(index);
  });

  test.each([null, undefined, "", "Core", "practice", "3", "0"])("%p is not a page of the lesson", (value) => {
    expect(PageLinks.indexOf(value)).toBeNull();
  });
});

describe("PageLinks.href", () => {
  test("a page opens the lesson tab at that page", () => {
    expect(PageLinks.href("abc", "core")).toBe("/lessons/abc?tab=lesson&page=core");
  });

  test("no page, or a page that does not exist, opens the lesson", () => {
    expect(PageLinks.href("abc", "")).toBe("/lessons/abc?tab=lesson");
    expect(PageLinks.href("abc", null)).toBe("/lessons/abc?tab=lesson");
    expect(PageLinks.href("abc", "nope")).toBe("/lessons/abc?tab=lesson");
  });
});

describe("PageLinks.where", () => {
  test("a page and its section are named in plain words", () => {
    expect(PageLinks.where({ page: "core", heading: "How halving works" })).toBe("Core page · How halving works");
  });

  test("a page without a section is just the page", () => {
    expect(PageLinks.where({ page: "advanced", heading: "" })).toBe("Advanced page");
  });

  test("a concept that could not be placed has no place to name", () => {
    expect(PageLinks.where({ page: "", heading: "" })).toBe("");
  });
});

describe("PageLinks.words", () => {
  test("the button says what it opens: a page, or the whole lesson", () => {
    expect(PageLinks.button({ page: "core" })).toBe("Study this");
    expect(PageLinks.button({ page: "" })).toBe("Open the lesson");
  });
});

describe("PageLinks.fromQuery", () => {
  test("the page to open is the page= of the address, when it is one of the lesson's pages", () => {
    expect(PageLinks.fromQuery("advanced")).toBe(2);
    expect(PageLinks.fromQuery("core ")).toBeNull();
    expect(PageLinks.fromQuery(null)).toBeNull();
  });
});

describe("PageLinks.study", () => {
  const links = [
    { concept: "Halving", page: "core", heading: "How halving works" },
    { concept: "Cost", page: "", heading: "" },
  ];

  test("a topic with a page links to it, naming where it is", () => {
    expect(PageLinks.study("abc", links, "Halving")).toEqual({
      href: "/lessons/abc?tab=lesson&page=core", where: "Core page · How halving works", button: "Study this",
    });
  });

  test("a topic with no page opens the lesson", () => {
    expect(PageLinks.study("abc", links, "Cost")).toEqual({ href: "/lessons/abc?tab=lesson", where: "", button: "Open the lesson" });
  });

  test("a topic the server did not link (an older answer) opens the lesson too", () => {
    expect(PageLinks.study("abc", links, "Other")).toEqual({ href: "/lessons/abc?tab=lesson", where: "", button: "Open the lesson" });
    expect(PageLinks.study("abc", undefined, "Other")?.button).toBe("Open the lesson");
  });
});
