import { AlertCircleIcon, AlertTriangleIcon, CircleCheckIcon, InfoIcon, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/console/empty-state";
import { buttonVariants } from "@/components/ui/button";
import { type AttentionTone, AttentionActions } from "@/lib/console-charts";
import type { Attention } from "@/lib/types";
import { cn } from "@/lib/utils";

const ICONS: Record<AttentionTone, { icon: LucideIcon; box: string; word: string }> = {
  bad: { icon: AlertCircleIcon, box: "bg-destructive-soft text-destructive-text", word: "Problem" },
  warn: { icon: AlertTriangleIcon, box: "bg-marigold-soft text-marigold-text", word: "Warning" },
  info: { icon: InfoIcon, box: "bg-primary-soft text-primary-text", word: "Note" },
};

/** What needs a person, most serious first, each with a button to the page where it can be dealt with. */
export function AttentionCard({ items }: { items: readonly Attention[] }) {
  return (
    <section aria-label="Needs attention" className="min-w-0 rounded-2xl border bg-card shadow-card">
      <div className="flex items-center justify-between gap-3 px-[18px] pt-4">
        <h2 className="font-sans text-base font-extrabold">Needs attention</h2>
        <Link href="/console/runs" className={buttonVariants({ variant: "outline", size: "sm" })}>
          All runs
        </Link>
      </div>
      <div className="px-2 pt-2 pb-3">
        {items.length === 0 ? (
          <EmptyState icon={CircleCheckIcon} title="All clear" description="No failing lessons, struggling models or missing keys right now." />
        ) : (
          <ul className="grid gap-0.5">
            {items.map((item) => {
              const view = AttentionActions.of(item);
              const { icon: Icon, box, word } = ICONS[view.tone];
              return (
                <li key={`${item.kind}-${item.title}`} className="grid grid-cols-[30px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-xl p-2.5 hover:bg-muted">
                  <span className={cn("grid size-[30px] place-items-center rounded-[9px]", box)}>
                    <Icon className="size-4" aria-hidden="true" />
                    <span className="sr-only">{word}</span>
                  </span>
                  <div className="min-w-0">
                    <b className="block text-[13.5px]">{item.title}</b>
                    <p className="text-[12.5px] text-muted-foreground">{item.detail}</p>
                  </div>
                  <Link href={view.href} className={buttonVariants({ variant: "outline", size: "sm" })}>
                    {view.actionLabel}
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
