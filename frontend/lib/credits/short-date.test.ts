/**
 * Unit under test: `ShortDate`, "Fri 14 Nov" the same in every browser.
 *
 * Why: the wallet, the history and the buy page all show dates, and `Intl` puts a comma after the weekday in some
 * locales and not in others. A date that reads differently on two machines is also a test that passes on one of them.
 *
 * Use cases:
 * - the weekday, the day and the month, with no comma
 * - a single-digit day is not padded
 */
import { expect, test } from "bun:test";

import { ShortDate } from "./short-date";

test("the weekday, the day and the month, with no comma", () => {
  expect(ShortDate.of(new Date(2026, 10, 14, 12))).toBe("Sat 14 Nov");
});

test("a single-digit day is not padded", () => {
  expect(ShortDate.of(new Date(2026, 10, 5, 12))).toBe("Thu 5 Nov");
});
