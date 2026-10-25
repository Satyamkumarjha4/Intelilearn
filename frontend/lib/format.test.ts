/**
 * Unit under test: `DateText`, dates as a learner reads them.
 *
 * Why: the read-only views say when something was submitted; a broken date must read as nothing, not "Invalid Date".
 *
 * Use cases:
 * - an ISO timestamp becomes a medium date in the given language
 * - text that is not a date becomes an empty string
 */
import { expect, test } from "bun:test";

import { DateText } from "./format";

test("an ISO timestamp becomes a medium date", () => {
  expect(DateText.day("2026-10-24T12:04:00Z", "en-US")).toBe("Oct 24, 2026");
  expect(DateText.day("2026-10-24T12:04:00Z", "en-GB")).toBe("24 Oct 2026");
});

test("text that is not a date becomes nothing", () => {
  expect(DateText.day("soon")).toBe("");
  expect(DateText.day("")).toBe("");
});
