import { ApiError } from "@/lib/api";

import { WalletWords } from "./wallet-words";
import type { RepairOutlook, Streak, StreakDayState } from "./types";

/** One of the last 28 days as the calendar draws it. */
export type DayCell = { date: string; state: StreakDayState; weekday: string; dayOfMonth: number; isToday: boolean; label: string };

/** A repair that did not happen, in words; `buy` is true when more credits are what is missing. */
export type RepairFailure = { message: string; buy: boolean };

const STATE_WORDS: Record<StreakDayState, string> = {
  active: "you studied",
  repaired: "repaired",
  missed: "no study",
  pending: "today",
};

/** The streak page in a learner's words. The dates and the counts are the server's, in the learner's own time zone. */
export class StreakView {
  static headline(streak: Streak): string {
    const days = streak.alive ? streak.current : 0;
    if (days === 0) return "No streak yet";
    return `${days}-day streak`;
  }

  static today(streak: Streak): string {
    if (streak.today.done) return "You've studied today. Nice work!";
    return streak.alive && streak.current > 0 ? "Do a little today to keep your streak going." : "Do a little today to start a streak.";
  }

  static best(streak: Streak): string {
    return streak.longest === 1 ? "Best: 1 day" : `Best: ${streak.longest} days`;
  }

  static nextBonus(streak: Streak): string {
    const { days_to_go: toGo, credits } = streak.next_bonus;
    const prize = WalletWords.credits(credits);
    if (toGo <= 0) return `Your next bonus is ${prize}, today.`;
    return `${toGo === 1 ? "1 more day" : `${toGo} more days`} to your next bonus: ${prize}.`;
  }

  static cells(streak: Streak): DayCell[] {
    return streak.days.map((day) => {
      const at = new Date(`${day.date}T12:00:00`);
      const isToday = day.date === streak.today.date;
      const named = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" }).format(at);
      return {
        date: day.date,
        state: day.state,
        weekday: new Intl.DateTimeFormat("en-GB", { weekday: "narrow" }).format(at),
        dayOfMonth: at.getDate(),
        isToday,
        label: `${named}: ${isToday && day.state === "pending" ? "not yet" : STATE_WORDS[day.state]}`,
      };
    });
  }

  /** The button's words, or why there is nothing to repair. */
  static repairTitle(repair: RepairOutlook): string {
    return `Repair yesterday for ${WalletWords.credits(repair.cost)}`;
  }

  static repairLeft(repair: RepairOutlook): string {
    const week = repair.left_week === 1 ? "1 repair" : `${repair.left_week} repairs`;
    const month = repair.left_month === 1 ? "1" : String(repair.left_month);
    return `${week} left this week, ${month} left this month.`;
  }

  static repairReason(repair: RepairOutlook): string {
    if (repair.reason === "repair_limit") return "You've used your repairs for now. They come back as the days go by.";
    return "Nothing to repair: you didn't miss yesterday.";
  }

  static repaired(day: string, cost: number, bonus: number): string {
    const base = `Yesterday counts again (${WalletWords.credits(cost)}).`;
    return bonus > 0 ? `${base} And that brought a bonus of ${WalletWords.credits(bonus)}!` : base;
  }

  static failure(error: unknown): RepairFailure {
    if (error instanceof ApiError) {
      if (error.status === 402) return { message: error.message || "You don't have enough credits to repair yesterday.", buy: true };
      if (error.code === "nothing_to_repair") return { message: "Nothing to repair: you didn't miss yesterday.", buy: false };
      if (error.code === "repair_limit") return { message: "You've used your repairs for now. They come back as the days go by.", buy: false };
      return { message: error.message || "We couldn't repair yesterday.", buy: false };
    }
    return { message: "We couldn't repair yesterday. Please try again.", buy: false };
  }
}
