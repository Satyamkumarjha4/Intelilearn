"use client";

import { TimerIcon } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts";

import { ChartCard } from "@/components/console/chart-card";
import { ChartTip, GRID, TICK, barSegment, shorten } from "@/components/console/chart-parts";
import { EmptyState } from "@/components/console/empty-state";
import { ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { RangeWords, SlowestSteps, type StepBar } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import type { ConsoleOverview } from "@/lib/types";

const ROW_HEIGHT = 32;

/** The p95 time of the slowest lesson steps, as horizontal bars (one measure, so one colour). */
export function SlowestStepsCard({ steps, range }: { steps: ConsoleOverview["slowest_steps"]; range: ConsoleOverview["range"] }) {
  const bars = SlowestSteps.rows(steps);

  return (
    <ChartCard
      title="Slowest steps"
      subtitle={`p95 time per lesson step, ${RangeWords.of(range)}`}
      summary={bars.length ? `Horizontal bars of the slowest steps: ${bars.map((bar) => `${bar.node} ${bar.label}`).join(", ")}.` : "No step timings in this period."}
      table={SlowestSteps.table(bars)}
    >
      {bars.length ? (
        <ChartContainer config={{ seconds: { label: "p95", color: "var(--primary)" } }} className="aspect-auto w-full" style={{ height: bars.length * ROW_HEIGHT + 34 }}>
          <BarChart data={bars} layout="vertical" margin={{ top: 0, right: 56, left: 0, bottom: 0 }} barSize={16}>
            <CartesianGrid horizontal={false} {...GRID} />
            <XAxis type="number" tickLine={false} axisLine={false} tick={TICK} tickFormatter={ConsoleFormat.durationAxis} />
            <YAxis type="category" dataKey="node" tickLine={false} axisLine={false} tick={TICK} width={150} tickFormatter={(node: string) => shorten(node, 22)} />
            <ChartTooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }} content={<ChartTip<StepBar> build={SlowestSteps.tooltip} />} />
            <Bar dataKey="seconds" fill="var(--primary)" isAnimationActive={false} shape={(props) => barSegment(props, "var(--primary)", "right")}>
              <LabelList dataKey="label" position="right" style={TICK} />
            </Bar>
          </BarChart>
        </ChartContainer>
      ) : (
        <EmptyState icon={TimerIcon} title="No step timings yet" description="Once lessons have been built in this period, the slowest steps show up here." />
      )}
    </ChartCard>
  );
}
