/**
 * Unit under test: `Initials`, the letters in a person's round avatar.
 *
 * Why: the header and the console sidebar both show one. A staff account made from the command line has no name, and a
 * "?" there looks like a bug; the email always exists, so it stands in.
 *
 * Use cases:
 * - a name gives the first letters of up to two words, in capitals
 * - a person with no name is shown by the first letter of their email
 * - a name of only spaces counts as no name, and nothing at all is "?"
 */
import { describe, expect, test } from "bun:test";

import { Initials } from "./initials";

describe("Initials.of", () => {
  test.each([
    [{ name: "Asha Learner", email: "a@example.com" }, "AL"],
    [{ name: "ravi", email: "r@example.com" }, "R"],
    [{ name: "  Maria  del Carmen ", email: "m@example.com" }, "MD"],
    [{ name: "", email: "staff@example.com" }, "S"],
    [{ name: "   ", email: "staff@example.com" }, "S"],
    [{ name: "", email: "" }, "?"],
    [null, "?"],
  ])("%j is %s", (person, letters) => {
    expect(Initials.of(person)).toBe(letters);
  });
});
