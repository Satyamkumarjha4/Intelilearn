/**
 * Unit under test: `CodeEntry`, what a person types or pastes into the box for the emailed code.
 *
 * Why: people paste `123 456` or `123-456` straight from the email, add a stray space or type a letter. A box that keeps any
 * of that sends a code the server will refuse, and the person is told the code "didn't work" when it was right.
 *
 * Use cases:
 * - spaces, dashes and letters are dropped and only the digits stay, in order
 * - more digits than the code has are cut off
 * - a code is complete at exactly six digits, and not before
 * - the six boxes show one digit each and are blank where nothing is typed
 */
import { describe, expect, test } from "bun:test";

import { CodeEntry } from "./code-entry";

describe("digits", () => {
  test.each([
    ["123456", "123456"],
    ["123 456", "123456"],
    ["123-456", "123456"],
    [" 12a3b4 56 ", "123456"],
    ["abc", ""],
    ["", ""],
    ["1234567", "123456"],
    ["١٢٣٤٥٦", ""], // another script's digits are not ours
  ])("%p becomes %p", (raw, digits) => {
    expect(CodeEntry.digits(raw)).toBe(digits);
  });

  test("the length can differ", () => {
    expect(CodeEntry.digits("12345678", 8)).toBe("12345678");
    expect(CodeEntry.digits("12345678", 4)).toBe("1234");
  });
});

describe("isComplete", () => {
  test("only at six digits", () => {
    expect(CodeEntry.isComplete("12345")).toBe(false);
    expect(CodeEntry.isComplete("123 456")).toBe(true);
    expect(CodeEntry.isComplete("12345a")).toBe(false);
  });
});

describe("boxes", () => {
  test("one digit each, blank where nothing is typed", () => {
    expect(CodeEntry.boxes("12")).toEqual(["1", "2", "", "", "", ""]);
    expect(CodeEntry.boxes("")).toEqual(["", "", "", "", "", ""]);
    expect(CodeEntry.boxes("1234567")).toEqual(["1", "2", "3", "4", "5", "6"]);
  });
});
