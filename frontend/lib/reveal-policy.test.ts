/**
 * Unit under test: `RevealPolicy`, which parts of the landing page wait to pop in as they scroll into view.
 *
 * Why: content must be there for everyone, so only what is below the fold is held back, and only once the browser has
 * script. The same rule sets the stagger: items in a group come in a beat apart, not all at once.
 *
 * Use cases:
 * - something near the top of the screen shows at once; something below the fold waits
 * - the line between the two is just short of the bottom edge (92% of the screen)
 * - items in a group are staggered 80 ms apart, the first with no delay
 */
import { describe, expect, test } from "bun:test";

import { RevealPolicy } from "./reveal-policy";

describe("RevealPolicy", () => {
  test("what is on screen shows at once, what is below the fold waits", () => {
    expect(RevealPolicy.startsHidden(100, 800)).toBe(false);
    expect(RevealPolicy.startsHidden(1200, 800)).toBe(true);
  });

  test("the line is 92% of the screen's height", () => {
    expect(RevealPolicy.startsHidden(736, 800)).toBe(false);
    expect(RevealPolicy.startsHidden(737, 800)).toBe(true);
  });

  test("items in a group are staggered 80 ms apart, the first on time", () => {
    expect([0, 1, 3].map((n) => RevealPolicy.delay(n))).toEqual(["0s", "0.08s", "0.24s"]);
  });
});
