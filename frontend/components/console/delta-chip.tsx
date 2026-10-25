import type { DeltaTone } from "@/lib/console-charts";
import { cn } from "@/lib/utils";

const TONES: Record<DeltaTone, string> = {
  good: "bg-success-soft text-success-text",
  bad: "bg-destructive-soft text-destructive-text",
  neutral: "bg-muted text-muted-foreground",
};

/** A change since the period before ("+12%"). The sign is in the text, so colour is never the only signal. */
export function DeltaChip({ label, tone }: { label: string; tone: DeltaTone }) {
  return <span className={cn("rounded-full px-2 py-px font-mono text-[11.5px] tabular-nums", TONES[tone])}>{label}</span>;
}
