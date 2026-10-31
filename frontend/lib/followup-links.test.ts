/**
 * Unit under test: `FollowupLinks`, the links between a lesson and the lessons made from it.
 *
 * Why: a follow-up is a lesson of its own, so nothing on its page says where it came from unless the page does; and a
 * learner who made a Foundation lesson and then lost the tab has no other way back. Links must go both ways, name the
 * lesson, and be absent when there is nothing to link (a deleted parent, or a follow-up not made yet).
 *
 * Use cases:
 * - a follow-up links to the lesson it was made from, "Made from: <title>"
 * - a lesson links to its Foundation and Advanced lessons, Foundation first, each by its title, and only those that exist
 * - a lesson with no parent and no follow-ups has nothing to show
 * - a follow-up of a deleted parent shows no "Made from"
 * - a lesson can be both: made from one lesson and the parent of another
 */
import { describe, expect, test } from "bun:test";

import { FollowupLinks } from "./followup-links";
import type { LessonDetail } from "./types";

type Input = Pick<LessonDetail, "followup_of" | "followups">;
const none: Input = { followup_of: null, followups: { foundation: null, advanced: null } };

describe("FollowupLinks.of", () => {
  test("a follow-up links to where it came from", () => {
    const view = FollowupLinks.of({ ...none, followup_of: { id: "p1", title: "Binary search", level: "foundation" } });

    expect(view.madeFrom).toEqual({ label: "Made from", title: "Binary search", href: "/lessons/p1" });
    expect(view.followups).toEqual([]);
  });

  test("a lesson links to the follow-ups it has, Foundation first", () => {
    const view = FollowupLinks.of({
      ...none,
      followups: { advanced: { id: "a1", title: "Advanced Binary search" }, foundation: { id: "f1", title: "Foundations of Binary search" } },
    });

    expect(view.followups).toEqual([
      { label: "Foundation lesson", title: "Foundations of Binary search", href: "/lessons/f1" },
      { label: "Advanced lesson", title: "Advanced Binary search", href: "/lessons/a1" },
    ]);
    expect(view.madeFrom).toBeNull();
  });

  test("only the follow-ups that exist are linked", () => {
    const view = FollowupLinks.of({ ...none, followups: { foundation: null, advanced: { id: "a1", title: "Advanced X" } } });

    expect(view.followups.map((l) => l.label)).toEqual(["Advanced lesson"]);
  });

  test("a lesson with no parent and no follow-ups has nothing to show", () => {
    expect(FollowupLinks.any(FollowupLinks.of(none))).toBe(false);
  });

  test("a follow-up whose parent was deleted shows no 'Made from'", () => {
    expect(FollowupLinks.of(none).madeFrom).toBeNull();
  });

  test("a lesson can be both made from one and the parent of another", () => {
    const view = FollowupLinks.of({
      followup_of: { id: "p1", title: "Parent", level: "advanced" },
      followups: { foundation: { id: "f1", title: "Child" }, advanced: null },
    });

    expect(FollowupLinks.any(view)).toBe(true);
    expect(view.madeFrom?.href).toBe("/lessons/p1");
    expect(view.followups).toHaveLength(1);
  });
});
