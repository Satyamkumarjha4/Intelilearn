import type { MeterTone } from "@/lib/console-charts";
import { cn } from "@/lib/utils";

const FILLS: Record<MeterTone, string> = { primary: "bg-primary", marigold: "bg-marigold", destructive: "bg-destructive" };

/** A thin bar showing a share of something (0 to 1): lessons that finished, the month's budget. */
export function Meter({ fraction, tone, label }: { fraction: number; tone: MeterTone; label: string }) {
  const percent = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="h-[7px] overflow-hidden rounded-md bg-muted">
      <span className={cn("block h-full rounded-md", FILLS[tone])} style={{ width: `${percent}%` }} />
    </div>
  );
}
