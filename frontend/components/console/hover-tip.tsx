import { TooltipFrame } from "@/components/console/chart-parts";
import type { TooltipData } from "@/lib/console-charts";
import { cn } from "@/lib/utils";

/** A hover (and keyboard focus) box for a mark that is not a Recharts chart, such as a funnel row. */
export function HoverTip({ tip, children, className }: { tip: TooltipData; children: React.ReactNode; className?: string }) {
  return (
    <div tabIndex={0} className={cn("group/tip relative rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50", className)}>
      {children}
      <div role="tooltip" className="pointer-events-none absolute top-0 left-1/2 z-10 hidden -translate-x-1/2 -translate-y-full pb-1 group-hover/tip:block group-focus-visible/tip:block">
        <TooltipFrame {...tip} />
      </div>
    </div>
  );
}
