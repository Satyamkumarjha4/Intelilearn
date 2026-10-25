"use client";

import { useState } from "react";

import { TextTable } from "@/components/console/data-table";
import { cn } from "@/lib/utils";

export type LegendItem = { label: string; color: string; kind?: "square" | "tick" };

type Props = {
  title: string;
  subtitle?: string;
  /** Always given for two or more series. */
  legend?: readonly LegendItem[];
  /** What the chart says in a sentence, for people who cannot see it. */
  summary: string;
  /** The chart as a table; gives the card its "Show as table" switch. */
  table?: { headers: readonly string[]; rows: readonly (readonly string[])[] };
  children: React.ReactNode;
  className?: string;
};

/** A card for a chart: title, subtitle, legend, and a switch between the chart and the same numbers as a table. */
export function ChartCard({ title, subtitle, legend, summary, table, children, className }: Props) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section aria-label={title} className={cn("min-w-0 rounded-2xl border bg-card shadow-card", className)}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-[18px] pt-4">
        <div>
          <h2 className="font-sans text-base font-extrabold">{title}</h2>
          {subtitle ? <p className="text-[13px] font-semibold text-muted-foreground">{subtitle}</p> : null}
        </div>
        {legend && legend.length > 0 ? <Legend items={legend} /> : null}
      </div>
      <div className="px-[18px] pt-3 pb-4">
        {asTable && table ? (
          <TextTable caption={`${title}, as a table`} headers={table.headers} rows={table.rows} />
        ) : (
          <div role="img" aria-label={summary}>
            {children}
          </div>
        )}
        {table ? (
          <button type="button" aria-pressed={asTable} onClick={() => setAsTable((on) => !on)} className="mt-2 rounded text-[12.5px] font-extrabold text-primary-text outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {asTable ? "Show as chart" : "Show as table"}
          </button>
        ) : null}
      </div>
    </section>
  );
}

export function Legend({ items }: { items: readonly LegendItem[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3.5 gap-y-1 text-[12.5px] font-bold text-muted-foreground" aria-label="Legend">
      {items.map((item) => (
        <li key={item.label} className="inline-flex items-center gap-1.5">
          <i aria-hidden="true" className={cn("inline-block", item.kind === "tick" ? "h-3 w-0.5" : "size-2.5 rounded-[3px]")} style={{ background: item.color }} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
