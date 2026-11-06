/**
 * Unit under test: `WalletWords`, the wallet in a learner's words.
 *
 * Why: the server sends parcels of credits in the order they will be spent, each with a source and an expiry. A learner
 * should see "Daily credits, run out on Fri 14 Nov", with parcels that run out together merged, and never the machinery.
 *
 * Use cases:
 * - each source has a plain name; one the screen does not know is still "Credits", never the raw source
 * - expiry reads as never, today, tomorrow, or a date
 * - parcels of the same source that run out the same day are one line, in the server's order
 * - the same source on different days, or different sources on one day, stay apart
 * - what is set aside reads as being used for lessons being made, with the right singular
 * - no word of the machinery (hold, ledger, bucket, reserve) appears in any phrase
 */
import { describe, expect, test } from "bun:test";

import { WalletWords } from "./wallet-words";

const NOW = new Date(2026, 10, 5, 12, 0);
const at = (day: number, hour = 9) => new Date(2026, 10, day, hour).toISOString();

describe("names", () => {
  test("each source has a plain name and an unknown one is just credits", () => {
    expect(WalletWords.source("signup")).toBe("Welcome credits");
    expect(WalletWords.source("weekly_streak")).toBe("Weekly streak bonus");
    expect(WalletWords.source("subscription")).toBe("Plan credits");
    expect(WalletWords.source("something_new")).toBe("Credits");
  });
});

describe("expiry", () => {
  test("never, today, tomorrow, and a date", () => {
    expect(WalletWords.expiry(null, NOW)).toBe("Never run out");
    expect(WalletWords.expiry(at(5, 20), NOW)).toBe("Run out today");
    expect(WalletWords.expiry(at(6, 1), NOW)).toBe("Run out tomorrow");
    expect(WalletWords.expiry(at(14), NOW)).toBe("Run out on Sat 14 Nov");
  });
});

describe("groups", () => {
  test("parcels of one source that run out the same day are one line, in the server's order", () => {
    const groups = WalletWords.groups(
      [
        { source: "daily", remaining: 2, expires_at: at(8, 9) },
        { source: "daily", remaining: 3, expires_at: at(8, 18) },
        { source: "signup", remaining: 30, expires_at: null },
      ],
      NOW,
    );

    expect(groups.map((g) => [g.label, g.remaining, g.expiry])).toEqual([
      ["Daily credits", 5, "Run out on Sun 8 Nov"],
      ["Welcome credits", 30, "Never run out"],
    ]);
  });

  test("the same source on different days stays apart, and so do different sources on one day", () => {
    const groups = WalletWords.groups(
      [
        { source: "daily", remaining: 1, expires_at: at(8) },
        { source: "daily", remaining: 1, expires_at: at(9) },
        { source: "weekly_streak", remaining: 1, expires_at: at(9) },
      ],
      NOW,
    );

    expect(groups).toHaveLength(3);
  });

  test("a wallet with nothing in it has no lines", () => {
    expect(WalletWords.groups([], NOW)).toEqual([]);
  });
});

describe("what is set aside", () => {
  test("reads as being used for lessons being made", () => {
    expect(WalletWords.reserved(1)).toBe("1 credit being used for lessons being made");
    expect(WalletWords.reserved(4)).toBe("4 credits being used for lessons being made");
  });

  test("no phrase uses a word of the machinery", () => {
    const text = [WalletWords.NONE, WalletWords.reserved(3), WalletWords.expiry(null), ...["signup", "daily", "purchase", "subscription", "refund"].map(WalletWords.source)].join(" ");

    expect(text).not.toMatch(/\b(hold|ledger|bucket|reserve|gateway|webhook)\b/i);
  });
});
