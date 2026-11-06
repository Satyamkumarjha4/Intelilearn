import { StreakView } from "@/lib/credits/streak-view";
import type { Streak, StreakDayState } from "@/lib/credits/types";
import { cn } from "@/lib/utils";

const LOOK: Record<StreakDayState, string> = {
  active: "bg-primary text-primary-foreground",
  repaired: "bg-marigold-soft text-marigold-text",
  missed: "bg-muted text-muted-foreground",
  pending: "border-2 border-dashed border-primary text-primary-text",
};

/** The last 28 days, a week to a row. Each day says what it was out loud, not by colour alone. */
export function StreakCalendar({ streak }: { streak: Streak }) {
  const cells = StreakView.cells(streak);
  return (
    <ol className="grid grid-cols-7 gap-1.5" aria-label="The last 28 days" data-testid="streak-days">
      {cells.map((cell) => (
        <li
          key={cell.date}
          aria-label={cell.label}
          data-state={cell.state}
          data-date={cell.date}
          className={cn(
            "grid aspect-square min-w-0 place-items-center rounded-lg text-sm font-bold",
            LOOK[cell.state],
            cell.isToday && "ring-2 ring-ring ring-offset-2 ring-offset-background",
          )}
        >
          <span aria-hidden="true">{cell.dayOfMonth}</span>
        </li>
      ))}
    </ol>
  );
}
