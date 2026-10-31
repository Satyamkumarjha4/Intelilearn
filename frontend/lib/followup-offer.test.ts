/**
 * Unit under test: `FollowupOffers`, the words a learner reads when a result leads to an offer.
 *
 * Why: the offer is decided by the server, but how it is said decides whether it feels like help or like a verdict. The
 * spec is firm that Socra must not tell people they are wrong about their own level, and that a learner who rated
 * themselves low and failed rated themselves correctly. Every case therefore has to say what the result suggests, never
 * what the learner is, and a pop-up has to be easy to turn down.
 *
 * Use cases:
 * - an offer stored on an attempt is read back; anything that is not an offer this page knows is none
 * - each of the five cases has its own words, and the button says what it does: "Make a Foundation lesson", "Make an
 *   Advanced lesson" or "Open it" (with the lesson to open)
 * - a Foundation or Advanced offer is a pop-up with a way to turn it down; the low rater's suggestion is a quiet note with
 *   nothing to press
 * - an offer to open a lesson we cannot name has no button rather than a broken one
 * - no case calls the learner a beginner or an expert, says they were wrong, or uses a word the learner should not see
 */
import { describe, expect, test } from "bun:test";

import { FollowupOffers } from "./followup-offer";
import type { FollowupOffer } from "./types";

const offer = (kind: FollowupOffer["kind"], action: FollowupOffer["action"], lesson_id: string | null = null): FollowupOffer => ({ kind, action, lesson_id });
const ALL = [
  offer("foundation", "generate"), offer("foundation", "revisit", "f1"), offer("advanced", "generate"), offer("advanced", "open", "a1"),
  offer("inline_suggestion", "revisit_or_related"),
];

describe("parse", () => {
  test.each(ALL)("reads back %j", (stored) => {
    expect(FollowupOffers.parse({ ...stored })).toEqual(stored);
  });

  test("anything that is not an offer this page knows is none", () => {
    const strange = [null, undefined, 3, "foundation", [], {}, { kind: "foundation" }, { kind: "foundation", action: "buy" }, { kind: "x", action: "open" }];

    for (const raw of strange) expect(FollowupOffers.parse(raw)).toBeNull();
  });

  test("a missing or empty lesson id is none", () => {
    expect(FollowupOffers.parse({ kind: "advanced", action: "generate" })?.lesson_id).toBeNull();
    expect(FollowupOffers.parse({ kind: "advanced", action: "open", lesson_id: "" })?.lesson_id).toBeNull();
  });
});

describe("what each case says and does", () => {
  test("a Foundation lesson that does not exist is offered to be made", () => {
    const view = FollowupOffers.view(offer("foundation", "generate"));

    expect(view.surface).toBe("dialog");
    expect(view.title).toBe("Want to build up the basics?");
    expect(view.step).toEqual({ label: "Make a Foundation lesson", intent: "make", level: "foundation" });
    expect(view.skip).toBe("Not now");
  });

  test("a Foundation lesson that exists is opened, not made again", () => {
    const view = FollowupOffers.view(offer("foundation", "revisit", "f1"));

    expect(view.title).toBe("Your Foundation lesson is ready");
    expect(view.step).toEqual({ label: "Open it", intent: "open", lessonId: "f1" });
  });

  test("an Advanced lesson that does not exist is offered to be made", () => {
    const view = FollowupOffers.view(offer("advanced", "generate"));

    expect(view.title).toBe("Ready for more?");
    expect(view.step).toEqual({ label: "Make an Advanced lesson", intent: "make", level: "advanced" });
  });

  test("an Advanced lesson that exists is opened", () => {
    const view = FollowupOffers.view(offer("advanced", "open", "a1"));

    expect(view.title).toBe("Your Advanced lesson is waiting");
    expect(view.step).toEqual({ label: "Open it", intent: "open", lessonId: "a1" });
  });

  test("a low rater who failed gets a quiet note and nothing to press", () => {
    const view = FollowupOffers.view(offer("inline_suggestion", "revisit_or_related"));

    expect(view.surface).toBe("note");
    expect(view.step).toBeNull();
    expect(view.message).toContain("Going back over the lesson");
  });

  test.each([offer("foundation", "revisit"), offer("advanced", "open")])("an offer to open a lesson we cannot name has no button (%j)", (stored) => {
    expect(FollowupOffers.view(stored).step).toBeNull();
  });

  test("every pop-up can be turned down, and only pop-ups", () => {
    for (const stored of ALL) {
      const view = FollowupOffers.view(stored);
      expect(view.skip !== "").toBe(view.surface === "dialog");
    }
  });
});

describe("the words", () => {
  const words = ALL.flatMap((stored) => {
    const view = FollowupOffers.view(stored);
    return [view.title, view.message, view.step?.label ?? "", view.skip];
  }).join(" ");

  test("never call the learner a level or say they were wrong", () => {
    expect(words).not.toMatch(/\b(beginner|expert|proficient|novice|wrong|mistaken|should have|too low|too high|you rated)\b/i);
  });

  test("never use a word a learner should not see", () => {
    expect(words).not.toMatch(/\b(node|run|graph|pipeline|stage|llm|model|attempt|band|fail(ed|ure)?|score)\b/i);
  });

  test("the two buttons that make a lesson are named as the spec names them", () => {
    expect(words).toContain("Make a Foundation lesson");
    expect(words).toContain("Make an Advanced lesson");
  });
});
