import { Loader2Icon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Pill, PillTone } from "@/lib/lesson-status";

const VARIANT: Record<PillTone, "marigold" | "primary" | "success" | "insight" | "destructive-soft"> = {
  marigold: "marigold",
  primary: "primary",
  success: "success",
  insight: "insight",
  destructive: "destructive-soft",
};

/** A lesson's status, written as what is going on or what to do next. */
export function StatusPill({ pill }: { pill: Pill }) {
  return (
    <Badge variant={VARIANT[pill.tone]} className="max-w-full whitespace-normal py-1 text-left">
      {pill.spinner && <Loader2Icon className="size-3 shrink-0 motion-safe:animate-spin" aria-hidden="true" />}
      {pill.label}
    </Badge>
  );
}
