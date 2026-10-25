import { ChartCard } from "@/components/console/chart-card";
import { HoverTip } from "@/components/console/hover-tip";
import { FunnelChart, RangeWords } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import type { ConsoleOverview } from "@/lib/types";

/** Where the lessons of the range stop: each step as a share of the lessons started, and what became of the rest. */
export function FunnelCard({ funnel, range }: { funnel: ConsoleOverview["funnel"]; range: ConsoleOverview["range"] }) {
  const rows = FunnelChart.rows(funnel);
  const summary = rows.map((row) => `${row.label} ${ConsoleFormat.count(row.value)}`).join(", ");

  return (
    <ChartCard title="Where lessons stop" subtitle={RangeWords.of(range)} summary={`Funnel of lessons: ${summary}.`} table={FunnelChart.table(rows)}>
      <ol className="grid gap-2.5">
        {rows.map((row) => (
          <li key={row.key}>
            <HoverTip tip={FunnelChart.tooltip(row)} className="grid grid-cols-[130px_minmax(0,1fr)_54px] items-center gap-x-2.5 gap-y-1 text-[13px] font-bold max-[560px]:grid-cols-[96px_minmax(0,1fr)_44px]">
              <span>{row.label}</span>
              <span className="h-[22px] overflow-hidden rounded-md bg-muted">
                <span className="block h-full rounded-r-md bg-primary" style={{ width: `${row.value > 0 ? Math.max(row.share, 1) : 0}%` }} />
              </span>
              <span className="text-right font-mono tabular-nums">{ConsoleFormat.count(row.value)}</span>
              {row.note ? <span className="col-span-2 col-start-2 -mt-0.5 text-[11.5px] font-semibold text-muted-foreground">{row.note}</span> : null}
            </HoverTip>
          </li>
        ))}
      </ol>
    </ChartCard>
  );
}
