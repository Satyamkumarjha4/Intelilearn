import type { HealthPillData } from "@/lib/console-charts";
import { cn } from "@/lib/utils";

/** "Database 4 ms": a dependency's state at a glance (a green dot when it answers, marigold when it does not). */
export function HealthPill({ label, detail, ok }: Omit<HealthPillData, "key">) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-[12.5px] font-extrabold">
      <span aria-hidden="true" className={cn("size-2 rounded-full", ok ? "bg-success" : "bg-marigold")} />
      {label}
      <span className="font-mono font-medium text-muted-foreground">{detail}</span>
      <span className="sr-only">{ok ? "working" : "has a problem"}</span>
    </span>
  );
}
