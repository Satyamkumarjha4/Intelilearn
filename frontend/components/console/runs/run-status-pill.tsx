import { Badge } from "@/components/ui/badge";
import type { StatusTone } from "@/lib/run-text";
import { cn } from "@/lib/utils";

const VARIANT: Record<StatusTone, "success" | "destructive-soft" | "primary" | "marigold" | "secondary"> = {
  ok: "success",
  bad: "destructive-soft",
  run: "primary",
  wait: "marigold",
  off: "secondary",
};

/** A status as a small pill with a dot, the console's way of showing a run or a model call's result. */
export function RunStatusPill({ label, tone, className }: { label: string; tone: StatusTone; className?: string }) {
  return (
    <Badge variant={VARIANT[tone]} className={cn("gap-1.5 py-0.5", tone === "off" && "text-muted-foreground", className)}>
      <span aria-hidden="true" className="size-[7px] rounded-full bg-current" />
      {label}
    </Badge>
  );
}
