import { AlertTriangleIcon } from "lucide-react";

import { ChainChips } from "@/components/console/routing/chain-chips";
import { RoutingView } from "@/lib/routing-view";
import type { ConsoleRouting, NodeRouting } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  phases: ConsoleRouting["phases"];
  /** The steps as edited, by key. */
  current: ReadonlyMap<string, NodeRouting>;
  selected: string | null;
  changed: ReadonlySet<string>;
  failed: ReadonlySet<string>;
  onSelect: (key: string) => void;
};

/** Every step, grouped by phase: what it does, how hard it thinks, and which models it tries in which order. */
export function NodeList({ phases, current, selected, changed, failed, onSelect }: Props) {
  return (
    <div className="py-1.5">
      {phases.map((phase) => (
        <section key={phase.phase} aria-label={RoutingView.phase(phase.phase)}>
          <h3 className="px-[18px] pt-2.5 pb-1.5 font-sans text-[11.5px] font-extrabold tracking-wider text-muted-foreground uppercase">
            {RoutingView.phase(phase.phase)}
          </h3>
          <ul>
            {phase.nodes.map((saved) => {
              const node = current.get(saved.key) ?? saved;
              const on = node.key === selected;
              return (
                <li key={node.key}>
                  <button
                    type="button"
                    aria-current={on ? "true" : undefined}
                    onClick={() => onSelect(node.key)}
                    className={cn(
                      "grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1.5 border-l-[3px] border-transparent px-[18px] py-2.5 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
                      on && "border-primary bg-primary-soft hover:bg-primary-soft",
                    )}
                  >
                    <span className="min-w-0">
                      <span className={cn("font-mono text-[12.5px] font-semibold", !node.enabled && "opacity-50")}>{node.key}</span>
                      <span className="text-[12.5px] text-muted-foreground"> · {node.description}</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      {failed.has(node.key) ? (
                        <span className="inline-flex items-center gap-1 text-xs font-extrabold text-destructive-text">
                          <AlertTriangleIcon className="size-3.5" aria-hidden="true" /> Not saved
                        </span>
                      ) : changed.has(node.key) ? (
                        <span className="inline-flex items-center gap-1 text-xs font-extrabold text-marigold-text">
                          <i aria-hidden="true" className="size-2 rounded-full bg-marigold" /> Unsaved
                        </span>
                      ) : null}
                      <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-extrabold whitespace-nowrap text-muted-foreground">{RoutingView.effort(node)}</span>
                    </span>
                    <ChainChips node={node} className={cn("col-span-full", !node.enabled && "opacity-50")} />
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
