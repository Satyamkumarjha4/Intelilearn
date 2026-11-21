"use client";

import { DataTable, type Column } from "@/components/console/data-table";
import { EmptyState } from "@/components/console/empty-state";
import { StepTable, type StepRow } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import type { ConsoleUsage } from "@/lib/types";
import { ListXIcon } from "lucide-react";

const COLUMNS: Column<StepRow>[] = [
  { key: "node", header: "Step", sortValue: (row) => row.node, cell: (row) => <span className="font-mono text-[12.5px] font-semibold">{row.node}</span> },
  { key: "calls", header: "Calls", numeric: true, sortValue: (row) => row.calls, cell: (row) => ConsoleFormat.count(row.calls) },
  { key: "ok", header: "Worked", numeric: true, sortValue: (row) => row.ok_pct, cell: (row) => ConsoleFormat.percent(row.ok_pct) },
  { key: "retries", header: "Retries", numeric: true, sortValue: (row) => row.retries, cell: (row) => ConsoleFormat.count(row.retries) },
  { key: "fallbacks", header: "Fallbacks", numeric: true, sortValue: (row) => row.fallbacks, cell: (row) => ConsoleFormat.count(row.fallbacks) },
  { key: "tokens", header: "Tokens", numeric: true, sortValue: (row) => row.tokens_k, cell: (row) => `${ConsoleFormat.compact(row.tokens_k * 1000)}` },
  {
    key: "spend",
    header: "Spend",
    numeric: true,
    sortValue: (row) => row.spendValue,
    cell: (row) => (
      <span className="inline-flex items-center justify-end gap-2">
        <i aria-hidden="true" className="block h-2 rounded-sm bg-primary" style={{ width: Math.max(row.spendValue > 0 ? 2 : 0, Math.round(row.spendShare * 80)) }} />
        {ConsoleFormat.money(row.spendValue)}
      </span>
    ),
  },
  { key: "p95", header: "p95", numeric: true, sortValue: (row) => row.p95_s, cell: (row) => ConsoleFormat.duration(row.p95_s) },
];

/** Calls, success, retries, tokens and spend for each lesson step; the spend column carries a bar against the costliest step. */
export function StepsCard({ byNode }: { byNode: ConsoleUsage["by_node"] }) {
  return (
    <section aria-label="By lesson step" className="mt-4 min-w-0 rounded-2xl border bg-card shadow-card">
      <div className="px-[18px] pt-4">
        <h2 className="font-sans text-base font-extrabold">By lesson step</h2>
        <p className="text-[13px] font-semibold text-muted-foreground">Click a column to sort</p>
      </div>
      <div className="px-[18px] pt-2 pb-4">
        {byNode.length ? (
          <DataTable columns={COLUMNS} rows={StepTable.rows(byNode)} rowKey={(row) => row.node} caption="Usage by lesson step" defaultSort={{ key: "spend", direction: "desc" }} />
        ) : (
          <EmptyState icon={ListXIcon} title="No steps to show" description="No model calls match these filters." />
        )}
      </div>
    </section>
  );
}
