/**
 * Unit under test: `TestGuard`, which tabs of a lesson are closed while a test is in progress.
 *
 * Why: a test answered with the lesson open next to it measures nothing. The lesson's pages and the study sheets say
 * "Finish your test first" while an attempt is in progress; the test and the quick check answers stay open, and
 * nothing is closed once the attempt is over or while a retake is only being prepared.
 *
 * Use cases:
 * - the lesson and the study sheets are closed while an attempt is in progress
 * - the test and the quick check answers are never closed
 * - nothing is closed for any other state of the test (not started, preparing questions, grading, graded, failed)
 */
import { describe, expect, test } from "bun:test";

import type { TabId } from "./lesson-tabs";
import { TestGuard } from "./test-guard";
import type { TestStatus } from "./types";

const blocks = (tab: TabId, status: TestStatus) => TestGuard.blocks(tab, { test_status: status });

describe("while a test is in progress", () => {
  test.each(["lesson", "sheets"] as const)("the %s tab is closed", (tab) => {
    expect(blocks(tab, "in_progress")).toBe(true);
  });

  test.each(["test", "answers"] as const)("the %s tab stays open", (tab) => {
    expect(blocks(tab, "in_progress")).toBe(false);
  });
});

describe("at any other time", () => {
  test.each(["not_started", "generating", "grading", "graded", "failed"] as const)("nothing is closed when the test is %s", (status) => {
    for (const tab of ["lesson", "test", "sheets", "answers"] as const) expect(blocks(tab, status)).toBe(false);
  });
});

test("the words are kind and say what to do", () => {
  expect(TestGuard.TITLE).toBe("Finish your test first");
  expect(TestGuard.TEXT).toContain("Finish it");
  expect(TestGuard.BUTTON).toBe("Back to my test");
});
