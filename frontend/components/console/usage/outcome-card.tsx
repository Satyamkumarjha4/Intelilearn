"use client";

import { ChartNoAxesColumnIcon } from "lucide-react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { ChartCard } from "@/components/console/chart-card";
import { ChartTip, GRID, TICK, barSegment, shorten } from "@/components/console/chart-parts";
import { EmptyState } from "@/components/console/empty-state";
import { ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { OutcomeChart, type OutcomeRow, RangeWords } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import type { ConsoleUsage } from "@/lib/types";

const ROW_HEIGHT = 40;
const SHARE: Record<"ok" | "retried" | "failed", "okShare" | "retriedShare" | "failedShare"> = { ok: "okShare", retried: "retriedShare", failed: "failedShare" };

/** What came of each model's calls, as a 100% bar: worked first time, worked after a retry, failed (the status colours). */
export function OutcomeCard({ usage }: { usage: ConsoleUsage }) {
  const rows = OutcomeChart.rows(usage.by_model).filter((row) => row.total > 0);

  return (
    <ChartCard
      title="Calls by outcome"
      subtitle={`Per model, ${RangeWords.of(usage.range, usage.period)}`}
      legend={OutcomeChart.SERIES.map(({ label, color }) => ({ label, color }))}
      summary={rows.length ? `Share of each model's calls by outcome: ${rows.map((row) => `${row.model} ${ConsoleFormat.percent(row.okShare)} worked, ${ConsoleFormat.percent(row.retriedShare)} after a retry, ${ConsoleFormat.percent(row.failedShare)} failed`).join("; ")}.` : "No calls."}
      table={OutcomeChart.table(rows)}
    >
      {rows.length ? (
        <ChartContainer config={{}} className="aspect-auto w-full" style={{ height: rows.length * ROW_HEIGHT + 34 }}>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 0, bottom: 0 }} barSize={20}>
            <CartesianGrid horizontal={false} {...GRID} />
            <XAxis type="number" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickLine={false} axisLine={false} tick={TICK} tickFormatter={(value: number) => `${value}%`} />
            <YAxis type="category" dataKey="model" tickLine={false} axisLine={false} tick={TICK} width={150} tickFormatter={(model: string) => shorten(model, 22)} />
            <ChartTooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }} content={<ChartTip<OutcomeRow> build={OutcomeChart.tooltip} />} />
            {OutcomeChart.SERIES.map(({ key, color }) => (
              <Bar
                key={key}
                dataKey={SHARE[key]}
                stackId="outcome"
                fill={color}
                isAnimationActive={false}
                shape={(props) => barSegment(props, color, OutcomeChart.lastSegment(props.payload as OutcomeRow) === key ? "right" : "none", 8)}
              />
            ))}
          </BarChart>
        </ChartContainer>
      ) : (
        <EmptyState icon={ChartNoAxesColumnIcon} title="No calls" description="No model calls match these filters." />
      )}
    </ChartCard>
  );
}
