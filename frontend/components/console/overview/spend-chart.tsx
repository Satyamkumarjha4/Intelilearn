"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { ChartTip, GRID, TICK, barSegment } from "@/components/console/chart-parts";
import { ChartCard } from "@/components/console/chart-card";
import { EmptyState } from "@/components/console/empty-state";
import { ChartContainer, type ChartConfig, ChartTooltip } from "@/components/ui/chart";
import { ProviderSeries, SpendChart, type SpendRow } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import type { ConsoleOverview } from "@/lib/types";
import { CircleDollarSignIcon } from "lucide-react";

/** Daily AI spend, stacked by provider. A provider is always the same colour; only the top segment of a day is rounded. */
export function SpendCard({ daily }: { daily: ConsoleOverview["daily_spend"] }) {
  const data = SpendChart.shape(daily);
  const config: ChartConfig = Object.fromEntries(data.series.map((key) => [key, { label: ProviderSeries.label(key), color: ProviderSeries.color(key) }]));
  const spent = data.series.map((key) => `${ProviderSeries.label(key)} ${ConsoleFormat.money(data.rows.reduce((sum, row) => sum + (row[key] ?? 0), 0))}`);

  return (
    <ChartCard
      title="Daily AI spend"
      subtitle={`By provider, last ${data.rows.length} days`}
      legend={data.series.length > 1 ? data.series.map((key) => ({ label: ProviderSeries.label(key), color: ProviderSeries.color(key) })) : undefined}
      summary={data.total > 0 ? `Stacked bars of daily AI spend by provider over ${data.rows.length} days, ${ConsoleFormat.money(data.total)} in all: ${spent.join(", ")}.` : "No AI spend in this period."}
      table={SpendChart.table(data)}
    >
      {data.total > 0 ? (
        <ChartContainer config={config} className="aspect-auto h-[260px] w-full">
          <BarChart data={data.rows} margin={{ top: 8, right: 4, left: 0, bottom: 0 }} barCategoryGap="22%">
            <CartesianGrid vertical={false} {...GRID} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={TICK} minTickGap={14} />
            <YAxis tickLine={false} axisLine={false} tick={TICK} width={48} tickFormatter={ConsoleFormat.moneyAxis} />
            <ChartTooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }} content={<ChartTip<SpendRow> build={(row) => SpendChart.tooltip(row, data.series)} />} />
            {data.series.map((key) => (
              <Bar
                key={key}
                dataKey={key}
                stackId="spend"
                fill={ProviderSeries.color(key)}
                isAnimationActive={false}
                shape={(props) => barSegment(props, ProviderSeries.color(key), SpendChart.topSeries(props.payload as SpendRow, data.series) === key ? "top" : "none")}
              />
            ))}
          </BarChart>
        </ChartContainer>
      ) : (
        <EmptyState icon={CircleDollarSignIcon} title="No AI spend in this period" description="Model calls that cost money will show up here, day by day." />
      )}
    </ChartCard>
  );
}
