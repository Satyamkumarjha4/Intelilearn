"use client";

import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { type SortState, type SortValue, TableSort } from "@/lib/table-sort";
import { cn } from "@/lib/utils";

export type Column<T> = {
  key: string;
  header: string;
  /** Numbers and times line up on the right, in the mono face. */
  numeric?: boolean;
  /** What the column sorts by; leave it out for a column that does not sort. */
  sortValue?: (row: T) => SortValue;
  /** The first direction when the column is first clicked (numbers: biggest first; names: A to Z). */
  firstSort?: "asc" | "desc";
  cell: (row: T) => React.ReactNode;
};

type Props<T> = {
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  /** Read by screen readers as the table's name. */
  caption: string;
  defaultSort?: SortState;
  /** A height after which the table scrolls under its sticky header. */
  maxHeight?: number | string;
};

/**
 * A compact table. Headers are sticky; a table wider than its space scrolls sideways; a column with a `sortValue`
 * sorts on click and says so with `aria-sort`.
 */
export function DataTable<T>({ columns, rows, rowKey, caption, defaultSort, maxHeight }: Props<T>) {
  const [sort, setSort] = useState<SortState | null>(defaultSort ?? null);
  const column = columns.find((candidate) => candidate.key === sort?.key);
  const sorted = useMemo(() => TableSort.apply(rows, sort, (row) => column?.sortValue?.(row)), [rows, sort, column]);

  return (
    <div className="overflow-auto" style={{ maxHeight }} tabIndex={0} role="region" aria-label={caption}>
      <table className="w-full border-collapse text-[13.5px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                aria-sort={col.sortValue ? TableSort.ariaSort(sort, col.key) : undefined}
                className={cn("sticky top-0 z-[1] border-b bg-card px-3 py-2 text-left text-[11.5px] font-extrabold tracking-wide whitespace-nowrap text-muted-foreground uppercase", col.numeric && "text-right")}
              >
                {col.sortValue ? (
                  <button type="button" onClick={() => setSort(TableSort.next(sort, col.key, col.firstSort ?? (col.numeric ? "desc" : "asc")))} className="inline-flex items-center gap-1 rounded uppercase outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                    {col.header}
                    {sort?.key === col.key ? (
                      sort.direction === "asc" ? <ArrowUpIcon className="size-3" aria-hidden="true" /> : <ArrowDownIcon className="size-3" aria-hidden="true" />
                    ) : (
                      <ChevronsUpDownIcon className="size-3 opacity-50" aria-hidden="true" />
                    )}
                  </button>
                ) : (
                  col.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)} className="hover:bg-muted">
              {columns.map((col) => (
                <td key={col.key} className={cn("border-b border-border/60 px-3 py-2 align-middle", col.numeric && "text-right font-mono text-[12.5px] whitespace-nowrap tabular-nums")}>
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A plain table of strings: the "table view" of a chart. */
export function TextTable({ headers, rows, caption }: { headers: readonly string[]; rows: readonly (readonly string[])[]; caption: string }) {
  return (
    <div className="overflow-auto" tabIndex={0} role="region" aria-label={caption}>
      <table className="w-full border-collapse text-[13px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th key={header} scope="col" className={cn("border-b px-3 py-1.5 text-left text-[11.5px] font-extrabold tracking-wide whitespace-nowrap text-muted-foreground uppercase", index > 0 && "text-right")}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]} className="hover:bg-muted">
              {row.map((cell, index) => (
                <td key={`${row[0]}-${headers[index]}`} className={cn("border-b border-border/60 px-3 py-1.5", index > 0 && "text-right font-mono text-[12.5px] whitespace-nowrap tabular-nums")}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
