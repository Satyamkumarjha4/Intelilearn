"use client";

import { useState } from "react";

import { FilterBar, FilterDate, FilterSelect } from "@/components/console/filter-bar";
import { RangeToggle } from "@/components/console/range-toggle";
import { Button } from "@/components/ui/button";
import { ConsoleFormat } from "@/lib/console-format";
import { UsageFilterOptions } from "@/lib/console-filters";
import { ConsoleUrl } from "@/lib/console-url";
import type { CallOutcome, ConsoleModel, ConsoleProvider, UsageFilters, UsageRange } from "@/lib/types";

const RANGES: UsageRange[] = ["today", "7d", "30d", "custom"];
const RANGE_OPTIONS = RANGES.map((value) => ({ value, label: ConsoleFormat.rangeLabel(value) }));

type Props = {
  filters: UsageFilters;
  providers: readonly ConsoleProvider[];
  models: readonly ConsoleModel[];
  steps: readonly string[];
  onChange: (filters: UsageFilters) => void;
};

/** The usage page's filters. Every change goes to the address (`onChange`); a custom range only does once both dates are valid. */
export function UsageFilterBar({ filters, providers, models, steps, onChange }: Props) {
  const range = filters.range ?? "7d";
  const dates = { start: filters.start ?? "", end: filters.end ?? "" };
  const [draft, setDraft] = useState(dates);
  const [shown, setShown] = useState(dates);
  // The dates being typed follow the address when it changes by itself (back, a link): adjusted while rendering.
  if (shown.start !== dates.start || shown.end !== dates.end) {
    setShown(dates);
    setDraft(dates);
  }

  const editDate = (patch: Partial<typeof draft>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    if (ConsoleUrl.validDays(next.start, next.end)) onChange({ ...filters, ...next });
  };
  const badDates = range === "custom" && !ConsoleUrl.validDays(draft.start, draft.end);
  const change = (patch: Partial<UsageFilters>) => onChange(UsageFilterOptions.change(filters, patch, models));
  const narrowed = Boolean(filters.provider || filters.model || filters.node || filters.outcome);
  const today = ConsoleUrl.isoDay(new Date());

  return (
    <FilterBar label="Usage filters">
      <RangeToggle options={RANGE_OPTIONS} value={range} onChange={(next) => onChange(ConsoleUrl.withRange(filters, next))} />
      {range === "custom" ? (
        <>
          <FilterDate label="From" value={draft.start} max={draft.end || today} invalid={badDates} onChange={(start) => editDate({ start })} />
          <FilterDate label="To" value={draft.end} min={draft.start} max={today} invalid={badDates} onChange={(end) => editDate({ end })} />
          {badDates ? (
            <span role="alert" className="text-[12.5px] font-bold text-destructive-text">
              Pick two days in order, at most a year apart.
            </span>
          ) : null}
        </>
      ) : null}
      <FilterSelect label="Provider" value={filters.provider ?? ""} onChange={(provider) => change({ provider })} options={UsageFilterOptions.providers(providers)} />
      <FilterSelect label="Model" value={filters.model ?? ""} onChange={(model) => change({ model })} options={UsageFilterOptions.models(models, filters.provider ?? "")} />
      <FilterSelect label="Step" value={filters.node ?? ""} onChange={(node) => change({ node })} options={UsageFilterOptions.steps(steps)} />
      <FilterSelect label="Outcome" value={filters.outcome ?? ""} onChange={(outcome) => change({ outcome: outcome as CallOutcome | "" })} options={UsageFilterOptions.outcomes()} />
      {narrowed ? (
        <Button variant="ghost" size="sm" onClick={() => onChange({ ...filters, provider: "", model: "", node: "", outcome: "" })}>
          Clear filters
        </Button>
      ) : null}
    </FilterBar>
  );
}
