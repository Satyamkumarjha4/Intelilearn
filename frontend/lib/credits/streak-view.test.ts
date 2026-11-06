/**
 * Unit under test: `StreakView`, the streak page in a learner's words.
 *
 * Why: the counts and dates come from the server in the learner's own time zone; this only says them. The page must
 * tell someone with no streak how to start one, say plainly why a repair is not on offer, and show a refused repair
 * (not enough credits, nothing to repair, no repairs left) in words, never as a status code.
 *
 * Use cases:
 * - the headline is the current streak, or "No streak yet" (also when it is no longer alive)
 * - today's line differs for a day done, a streak to keep and a streak to start
 * - the best streak and the next bonus read with the right singular, including the day itself
 * - the last 28 days become cells with the weekday, day, whether it is today, and a spoken label
 * - the repair button, what is left, and why there is no repair
 * - a repair that happened says what it cost and any bonus it brought
 * - a refused repair: 402 can be fixed by buying; "nothing to repair" and "repair limit" cannot; anything else is generic
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "@/lib/api";

import { StreakView } from "./streak-view";
import type { RepairOutlook, Streak } from "./types";

const outlook = (over: Partial<RepairOutlook> = {}): RepairOutlook => ({ available: true, day: "2026-11-04", reason: null, cost: 1, left_week: 1, left_month: 3, ...over });

const streak = (over: Partial<Streak> = {}): Streak => ({
  current: 3, longest: 9, run_started_on: "2026-11-03", alive: true, zone: "Asia/Kolkata", today: { date: "2026-11-05", done: false },
  days: [{ date: "2026-11-04", state: "active" }, { date: "2026-11-05", state: "pending" }],
  next_bonus: { streak_day: 7, credits: 10, days_to_go: 4 }, repair: outlook(), ...over,
});

describe("the headline", () => {
  test("is the current streak, or none", () => {
    expect(StreakView.headline(streak())).toBe("3-day streak");
    expect(StreakView.headline(streak({ current: 0 }))).toBe("No streak yet");
    expect(StreakView.headline(streak({ current: 5, alive: false }))).toBe("No streak yet");
  });

  test("today's line follows what there is to do", () => {
    expect(StreakView.today(streak({ today: { date: "2026-11-05", done: true } }))).toBe("You've studied today. Nice work!");
    expect(StreakView.today(streak())).toBe("Do a little today to keep your streak going.");
    expect(StreakView.today(streak({ current: 0 }))).toBe("Do a little today to start a streak.");
  });

  test("the best and the next bonus", () => {
    expect(StreakView.best(streak({ longest: 1 }))).toBe("Best: 1 day");
    expect(StreakView.best(streak())).toBe("Best: 9 days");
    expect(StreakView.nextBonus(streak())).toBe("4 more days to your next bonus: 10 credits.");
    expect(StreakView.nextBonus(streak({ next_bonus: { streak_day: 7, credits: 10, days_to_go: 1 } }))).toBe("1 more day to your next bonus: 10 credits.");
    expect(StreakView.nextBonus(streak({ next_bonus: { streak_day: 7, credits: 1, days_to_go: 0 } }))).toBe("Your next bonus is 1 credit, today.");
  });
});

describe("the last 28 days", () => {
  test("become cells with a spoken label", () => {
    const cells = StreakView.cells(streak());

    expect(cells[0]).toMatchObject({ date: "2026-11-04", state: "active", dayOfMonth: 4, isToday: false });
    expect(cells[0].label).toBe("Wednesday 4 November: you studied");
    expect(cells[1]).toMatchObject({ isToday: true });
    expect(cells[1].label).toBe("Thursday 5 November: not yet");
  });

  test("a day studied today is labelled as studied, a missed one as no study", () => {
    const cells = StreakView.cells(streak({ days: [{ date: "2026-11-03", state: "missed" }, { date: "2026-11-04", state: "repaired" }, { date: "2026-11-05", state: "active" }] }));

    expect(cells.map((c) => c.label.split(": ")[1])).toEqual(["no study", "repaired", "you studied"]);
  });
});

describe("repairing yesterday", () => {
  test("the button, what is left and why not", () => {
    expect(StreakView.repairTitle(outlook())).toBe("Repair yesterday for 1 credit");
    expect(StreakView.repairLeft(outlook())).toBe("1 repair left this week, 3 left this month.");
    expect(StreakView.repairLeft(outlook({ left_week: 0, left_month: 1 }))).toBe("0 repairs left this week, 1 left this month.");
    expect(StreakView.repairReason(outlook({ available: false, reason: "repair_limit" }))).toContain("used your repairs");
    expect(StreakView.repairReason(outlook({ available: false, reason: "nothing_to_repair" }))).toContain("Nothing to repair");
  });

  test("a repair that happened says what it cost and any bonus", () => {
    expect(StreakView.repaired("2026-11-04", 1, 0)).toBe("Yesterday counts again (1 credit).");
    expect(StreakView.repaired("2026-11-04", 1, 10)).toBe("Yesterday counts again (1 credit). And that brought a bonus of 10 credits!");
  });
});

describe("a repair that was refused", () => {
  const refused = (status: number, code: string, message = "") => new ApiError(status, code, message);

  test("too few credits can be fixed by buying", () => {
    expect(StreakView.failure(refused(402, "insufficient_credits", "You need 1 credit for that and have 0."))).toEqual({
      message: "You need 1 credit for that and have 0.", buy: true,
    });
    expect(StreakView.failure(refused(402, "insufficient_credits")).message).toContain("enough credits");
  });

  test("nothing to repair and the limit cannot", () => {
    expect(StreakView.failure(refused(409, "nothing_to_repair"))).toMatchObject({ buy: false, message: expect.stringContaining("Nothing to repair") });
    expect(StreakView.failure(refused(409, "repair_limit"))).toMatchObject({ buy: false, message: expect.stringContaining("used your repairs") });
  });

  test("anything else is generic, and never a status code", () => {
    expect(StreakView.failure(refused(500, "error", "")).message).toBe("We couldn't repair yesterday.");
    expect(StreakView.failure(new Error("network")).message).toBe("We couldn't repair yesterday. Please try again.");
  });
});
