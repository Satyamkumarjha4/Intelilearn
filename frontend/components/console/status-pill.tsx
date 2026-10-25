import { cn } from "@/lib/utils";

export type StatusTone = "ok" | "warn" | "bad" | "run" | "wait" | "off";

const TONES: Record<StatusTone, string> = {
  ok: "bg-success-soft text-success-text",
  warn: "bg-marigold-soft text-marigold-text",
  bad: "bg-destructive-soft text-destructive-text",
  run: "bg-primary-soft text-primary-text",
  wait: "bg-marigold-soft text-marigold-text",
  off: "bg-muted text-muted-foreground",
};

/** A state in words with a dot ("Failed", "98%"). The words carry the meaning; the colour only helps. */
export function StatusPill({ tone, children, className }: { tone: StatusTone; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-extrabold whitespace-nowrap", TONES[tone], className)}>
      <span aria-hidden="true" className="size-[7px] rounded-full bg-current" />
      {children}
    </span>
  );
}
