"use client";

import { TimerIcon } from "lucide-react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { ChartCard } from "@/components/console/chart-card";
import { ChartTip, GRID, TICK, shorten } from "@/components/console/chart-parts";
import { EmptyState } from "@/components/console/empty-state";
import { ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { RoundedRect } from "@/lib/chart-shapes";
import { LatencyChart, type LatencyRow, ProviderSeries } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import type { ConsoleUsage } from "@/lib/types";

const ROW_HEIGHT = 40;

/** Call time per model: the median as a bar in the model's provider colour and the p95 as a tick at the end of its track. */
export function LatencyCard({ byModel }: { byModel: ConsoleUsage["by_model"] }) {
  const rows = LatencyChart.rows(byModel);
  const legend = [
    ...LatencyChart.series(rows).map((key) => ({ label: ProviderSeries.label(key), color: ProviderSeries.color(key) })),
    { label: "p95", color: "var(--foreground)", kind: "tick" as const },
  ];

  return (
    <ChartCard
      title="Call time by model"
      subtitle="Median (bar) and p95 (tick)"
      legend={legend}
      summary={rows.length ? `Call time per model, median and p95: ${rows.map((row) => `${row.model} ${ConsoleFormat.duration(row.median)} and ${ConsoleFormat.duration(row.p95)}`).join("; ")}.` : "No model call worked, so there are no call times."}
      table={LatencyChart.table(byModel)}
    >
      {rows.length ? (
        <ChartContainer config={{ p95: { label: "p95" } }} className="aspect-auto w-full" style={{ height: rows.length * ROW_HEIGHT + 34 }}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 0, bottom: 0 }} barSize={16}>
            <CartesianGrid horizontal={false} {...GRID} />
            <XAxis type="number" tickLine={false} axisLine={false} tick={TICK} tickFormatter={ConsoleFormat.durationAxis} />
            <YAxis type="category" dataKey="model" tickLine={false} axisLine={false} tick={TICK} width={150} tickFormatter={(model: string) => shorten(model, 22)} />
            <ChartTooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }} content={<ChartTip<LatencyRow> build={LatencyChart.tooltip} />} />
            {/* One bar as long as the p95 draws both marks, so the scale is shared and the tooltip has one row to read. */}
            <Bar
              dataKey="p95"
              isAnimationActive={false}
              shape={(props) => {
                const { x, y, width, height } = props as { x: number; y: number; width: number; height: number };
                const row = props.payload as LatencyRow;
                const { barWidth, tickX } = LatencyChart.geometry(width, row.median, row.p95);
                const d = RoundedRect.path(x, y, barWidth, height, 6, "right");
                return (
                  <g>
                    {d ? <path d={d} fill={ProviderSeries.color(row.series)} /> : null}
                    <rect x={x + tickX - 1} y={y - 3} width={2.5} height={height + 6} rx={1} fill="var(--foreground)" />
                  </g>
                );
              }}
            />
          </BarChart>
        </ChartContainer>
      ) : (
        <EmptyState icon={TimerIcon} title="No call times to show" description="No model call worked with these filters." />
      )}
    </ChartCard>
  );
}
