"use client";

import { SearchIcon } from "lucide-react";

import { RunFilters, type RunFilterState, type StatusTab } from "@/lib/run-filters";
import type { ConsoleGraph } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  filters: RunFilterState;
  /** What is typed in the search box, which runs ahead of the address while typing. */
  search: string;
  failed: { count: number; more: boolean } | null;
  onStatus: (status: StatusTab) => void;
  onJob: (job: ConsoleGraph | "") => void;
  onSearch: (text: string) => void;
};

const FIELD = "rounded-[10px] border-[1.5px] bg-card text-[13px] font-bold focus-within:ring-3 focus-within:ring-ring/50";

/** Status tabs, job, and search. Each change is for the address to hold (the page decides how). */
export function RunFilterBar({ filters, search, failed, onStatus, onJob, onSearch }: Props) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Status" className="inline-flex gap-0.5 rounded-[10px] bg-muted p-[3px]">
        {RunFilters.TABS.map((tab) => {
          const on = tab.id === filters.status;
          return (
            <button
              key={tab.id}
              type="button"
              aria-pressed={on}
              onClick={() => onStatus(tab.id)}
              className={cn(
                "rounded-lg px-3 py-1 text-[13px] font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                on ? "bg-card text-foreground shadow-[0_1px_0_var(--border)]" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {RunFilters.tabLabel(tab.id, failed?.count ?? null, failed?.more ?? false)}
            </button>
          );
        })}
      </div>

      <label className={cn(FIELD, "inline-flex items-center gap-1.5 px-2.5 py-1.5")}>
        <span className="text-muted-foreground">Job</span>
        <select
          value={filters.job}
          onChange={(event) => onJob(event.target.value as ConsoleGraph | "")}
          className="bg-transparent outline-none"
        >
          <option value="">All</option>
          {RunFilters.JOBS.map((job) => (
            <option key={job.id} value={job.id}>
              {job.label}
            </option>
          ))}
        </select>
      </label>

      <label className={cn(FIELD, "flex min-w-0 flex-1 items-center gap-1.5 px-2.5 py-1.5 text-muted-foreground sm:max-w-60 sm:flex-none sm:basis-60")}>
        <SearchIcon className="size-3.5 shrink-0" aria-hidden="true" />
        <input
          type="search"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Topic, learner or run ID"
          aria-label="Search runs"
          className="min-w-0 flex-1 bg-transparent font-semibold text-foreground outline-none placeholder:text-muted-foreground"
        />
      </label>
    </div>
  );
}
