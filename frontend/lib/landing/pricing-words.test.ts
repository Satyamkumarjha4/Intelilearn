/**
 * Unit under test: `PricingWords`, the landing page's pricing section worked out from `GET /api/public/pricing`.
 *
 * Why: a price on a public page that differs from the price charged is the worst kind of wrong, so this class holds no
 * price, credit count or "about N lessons" of its own: change a number in what the server says and the words change with
 * it. A number the server could not give is left out and never guessed, and a claim of one plan against another ("the
 * lowest price per credit", "less than half a top-up") is made only when the numbers show it.
 *
 * Use cases:
 * - money is rupees (paise only when there are some); a price a credit reads as "₹0.40 a credit"
 * - "about N full lessons" reads singular and plural and is left out when the server did not give it
 * - a cost range reads "2–3", or "2" when it is a single price; how long credits last reads "a year", "a week", "28 days"
 * - the buttons read "Start with N free credits", and "Start free" when there are no free credits or no price list; free
 *   credits are promised only when the server says there are some
 * - the cards are Free first, then each plan in the server's order, with their price, period, credits and lessons
 * - Free shows the sign-up credits, the lessons they make and what studying earns, with the 28-day bonus only when it is above 0
 * - Monthly Pro is the emphasised card with the best-value badge; the others have none
 * - the third line of a plan is only one the numbers back: several weeks when more than one can be bought, "the lowest price
 *   per credit" for the single cheapest, "less than half" or "cheaper" than a top-up when so, and nothing when not
 * - buttons lead to sign-up for a visitor and to the app for someone signed in
 * - the cost rows follow the live prices and skip a price the server left out
 * - the top-up line follows the one-time rules, and is absent when top-ups are off
 */
import { describe, expect, test } from "bun:test";

import { pricing } from "./fixtures";
import { PricingWords } from "./pricing-words";

const REGISTER = "/auth?mode=register";
const cards = (overrides = {}, signedIn = false) => PricingWords.cards(pricing(overrides), signedIn, REGISTER);
const card = (key: string, overrides = {}, signedIn = false) => cards(overrides, signedIn).find((c) => c.key === key)!;
const text = (lines: { bold?: string; text: string }[]) => lines.map((l) => `${l.bold ?? ""}${l.text}`);

describe("words for numbers", () => {
  test("money, a price a credit, lessons, ranges and spans", () => {
    expect(PricingWords.rupees(19900)).toBe("₹199");
    expect(PricingWords.perCredit(40)).toBe("₹0.40 a credit");
    expect(PricingWords.aboutLessons(1)).toBe("About 1 full lesson");
    expect(PricingWords.aboutLessons(10)).toBe("About 10 full lessons");
    expect(PricingWords.aboutLessons(null)).toBeNull();
    expect(PricingWords.range({ min: 2, max: 3 })).toBe("2–3");
    expect(PricingWords.range({ min: 2, max: 2 })).toBe("2");
    expect([365, 7, 28].map(PricingWords.lasts)).toEqual(["a year", "a week", "28 days"]);
    expect([PricingWords.plus(1), PricingWords.plus(10)]).toEqual(["+1 credit", "+10 credits"]);
  });

  test("the start button names the free credits, and says start free without them", () => {
    expect(PricingWords.startLabel(pricing())).toBe("Start with 30 free credits");
    expect(PricingWords.startLabel(pricing({ signup_credits: 50 }))).toBe("Start with 50 free credits");
    expect(PricingWords.startLabel(pricing({ signup_credits: 0 }))).toBe("Start free");
    expect(PricingWords.startLabel(null)).toBe("Start free");
  });

  test("free credits are promised only when the server says there are some", () => {
    expect([pricing(), pricing({ signup_credits: 0 }), null].map((p) => PricingWords.hasFreeCredits(p))).toEqual([true, false, false]);
  });
});

describe("the cards", () => {
  test("Free comes first and then the plans in the server's order", () => {
    expect(cards().map((c) => c.key)).toEqual(["free", "weekly_pro", "monthly_pro", "pro_plus"]);
  });

  test("a plan shows its price, period, credits and lessons from the numbers it was given", () => {
    const monthly = card("monthly_pro");

    expect([monthly.name, monthly.price, monthly.per]).toEqual(["Monthly Pro", "₹199", "/ 28 days"]);
    expect(text(monthly.lines).slice(0, 2)).toEqual(["500 credits for 28 days", "About 50 full lessons"]);
    expect(card("weekly_pro").per).toBe("/ week");
    expect(text(card("weekly_pro").lines).slice(0, 2)).toEqual(["100 credits a week", "About 10 full lessons a week"]);
  });

  test("a changed number changes the words: the page holds none of its own", () => {
    const edited = card("monthly_pro", { plans: pricing().plans.map((p) => (p.key === "monthly_pro" ? { ...p, price_paise: 17900, credits: 600, about_lessons: 60 } : p)) });

    expect(edited.price).toBe("₹179");
    expect(text(edited.lines).slice(0, 2)).toEqual(["600 credits for 28 days", "About 60 full lessons"]);
  });

  test("Free shows the sign-up credits, the lessons and what studying earns", () => {
    expect(text(card("free").lines)).toEqual([
      "30 credits that never expire",
      "About 3 full lessons",
      "+1 credit a day you study, +10 credits every 7-day streak, +10 credits more at 28 days",
    ]);
    expect([card("free").price, card("free").per]).toEqual(["₹0", null]);
  });

  test("the 28-day bonus is left out when it is 0, and the lessons when the server gave none", () => {
    const free = card("free", { monthly_streak_bonus: 0, signup_about_lessons: null });

    expect(text(free.lines)).toEqual(["30 credits that never expire", "+1 credit a day you study, +10 credits every 7-day streak"]);
  });

  test("only Monthly Pro is emphasised, with the best-value badge", () => {
    expect(cards().filter((c) => c.featured).map((c) => c.key)).toEqual(["monthly_pro"]);
    expect(card("monthly_pro").badge).toBe("Best value for regular study");
    expect(card("pro_plus").badge).toBeNull();
  });

  test("a plan's third line is only a claim the numbers back", () => {
    expect(text(card("weekly_pro").lines)[2]).toBe("Buy several weeks; they arrive one at a time");
    expect(text(card("pro_plus").lines)[2]).toBe("The lowest price per credit");
    expect(text(card("monthly_pro").lines)[2]).toBe("Less than half the price per credit of a top-up");
  });

  test("with a dearer plan the claim softens, and with no saving there is no claim", () => {
    const soft = pricing().plans.map((p) => (p.key === "monthly_pro" ? { ...p, price_paise_per_credit: 60 } : p));
    const same = pricing().plans.map((p) => (p.key === "monthly_pro" ? { ...p, price_paise_per_credit: 100 } : p));

    expect(text(card("monthly_pro", { plans: soft }).lines)[2]).toBe("Cheaper per credit than a top-up");
    expect(text(card("monthly_pro", { plans: same }).lines)[2]).toBeUndefined();
  });

  test("two plans at the same lowest price both go without the lowest-price claim", () => {
    const tied = pricing().plans.map((p) => (p.key !== "weekly_pro" ? { ...p, price_paise_per_credit: 30 } : p));

    expect(text(card("pro_plus", { plans: tied }).lines)[2]).toBe("Less than half the price per credit of a top-up");
  });

  test("with no top-up there is no comparison to make", () => {
    expect(text(card("monthly_pro", { one_time: null }).lines)[2]).toBeUndefined();
  });

  test("buttons lead to sign-up for a visitor, and to the app for someone signed in", () => {
    expect(card("monthly_pro").cta).toEqual({ label: "Choose Monthly Pro", href: REGISTER });
    expect(card("free").cta).toEqual({ label: "Start free", href: REGISTER });
    expect(card("monthly_pro", {}, true).cta.href).toBe("/buy");
    expect(card("free", {}, true).cta).toEqual({ label: "Go to my lessons", href: "/lessons" });
  });
});

describe("what credits buy and the top-up", () => {
  test("the rows follow the live prices", () => {
    expect(PricingWords.costRows(pricing())).toEqual([
      { label: "Full lesson with its Test", value: "10" },
      { label: "Retake, new questions", value: "2" },
      { label: "Cheat or revision sheet", value: "2–3" },
      { label: "Quick quiz", value: "1–4" },
    ]);
    expect(PricingWords.costRows(pricing({ lesson_credits: 12 }))[0].value).toBe("12");
  });

  test("a price the server left out is skipped, and a free one still shows", () => {
    const rows = PricingWords.costRows(pricing({ retake_credits: null, lesson_credits: 0 }));

    expect(rows.map((r) => r.label)).toEqual(["Full lesson with its Test", "Cheat or revision sheet", "Quick quiz"]);
    expect(rows[0].value).toBe("0");
  });

  test("the top-up line follows the one-time rules, and is absent when top-ups are off", () => {
    const line = PricingWords.topUp(pricing())!;

    expect(line.bold + line.text).toBe("Need just a few more? Top up at ₹1 a credit, 10 or more at a time, valid for a year, on top of any plan.");
    expect(PricingWords.topUp(pricing({ one_time: null }))).toBeNull();
  });
});
