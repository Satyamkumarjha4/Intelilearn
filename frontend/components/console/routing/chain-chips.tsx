import { ArrowRightIcon } from "lucide-react";

import { ProviderSeries } from "@/lib/console-charts";
import { RoutingView } from "@/lib/routing-view";
import type { NodeRouting } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A step's models in the order they are tried: a chip each, with an arrow to the next. */
export function ChainChips({ node, className }: { node: Pick<NodeRouting, "bindings">; className?: string }) {
  const chips = RoutingView.chain(node);
  return (
    <ol aria-label="Models in the order they are tried" className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {chips.map((chip, index) => (
        <li key={`${index}-${chip.full}`} className="flex items-center gap-1.5">
          {index > 0 ? <ArrowRightIcon className="size-3 text-muted-foreground" aria-hidden="true" /> : null}
          <span
            title={chip.parked ? `${chip.full} (switched off in this chain)` : chip.full}
            className={cn("inline-flex items-center gap-1.5 rounded-[7px] border-[1.5px] bg-card px-2 py-0.5 font-mono text-[11.5px]", chip.parked && "opacity-60 line-through")}
          >
            <i aria-hidden="true" className="size-2 rounded-[2px]" style={{ background: ProviderSeries.color(chip.series) }} />
            {chip.name}
          </span>
        </li>
      ))}
    </ol>
  );
}
