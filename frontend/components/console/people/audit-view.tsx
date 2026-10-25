"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ScrollTextIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { EmptyState } from "@/components/console/empty-state";
import { ErrorState } from "@/components/console/error-state";
import { PageHeader } from "@/components/console/page-header";
import { AuditRow } from "@/components/console/people/audit-row";
import { RangeToggle } from "@/components/console/range-toggle";
import { notFoundIfRefused } from "@/components/console/not-found-guard";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { useNow } from "@/components/lessons/use-now";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type AuditArea, AuditAreas } from "@/lib/console-audit";
import { peopleQueries } from "@/lib/console-people-queries";
import { consoleQueries } from "@/lib/console-queries";

const ALL = "all";
const OPTIONS = [{ value: ALL, label: "All" }, ...AuditAreas.OPTIONS];

/** The Change log. The area filter is in the address; the entries are filtered here, from the pages loaded so far, because
 *  the API pages the whole log (so "Show more" is also how to look further back for an area). */
export function AuditView() {
  const router = useRouter();
  const pathname = usePathname();
  const area = AuditAreas.parse(useSearchParams().get("area"));
  const now = new Date(useNow(true, 60_000));

  const log = notFoundIfRefused(useInfiniteQuery(peopleQueries.audit()));
  // A test of a model is kept by its id only; the model list says what it is called. The log reads fine without it.
  const models = useConsoleQuery(consoleQueries.models()).data;
  const modelNames = useMemo(() => new Map((models ?? []).map((model) => [String(model.id), model.name])), [models]);

  const loaded = useMemo(() => log.data?.pages.flatMap((page) => page.results) ?? [], [log.data]);
  const shown = useMemo(() => AuditAreas.filter(loaded, area), [loaded, area]);
  const areaLabel = AuditAreas.OPTIONS.find((option) => option.value === area)?.label.toLowerCase();

  return (
    <div>
      <PageHeader
        title="Change log"
        description="Every change made in the console, newest first."
        actions={
          <RangeToggle
            label="Area"
            options={OPTIONS}
            value={area || ALL}
            onChange={(next) => router.replace(`${pathname}${AuditAreas.query(next === ALL ? "" : (next as AuditArea))}`, { scroll: false })}
          />
        }
      />

      <section aria-label="Changes" aria-busy={log.isFetching && !log.isFetchingNextPage} className="min-w-0 rounded-2xl border bg-card px-[18px] py-2 shadow-card">
        {log.error && !log.data ? (
          <div className="py-4">
            <ErrorState message="The change log could not be loaded." onRetry={() => void log.refetch()} />
          </div>
        ) : log.isPending ? (
          <div role="status" aria-label="Loading the change log" className="grid gap-2 py-3">
            {Array.from({ length: 6 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : shown.length === 0 ? (
          <EmptyState
            icon={ScrollTextIcon}
            title={area ? `No ${areaLabel} changes among the newest ${loaded.length}` : "No changes yet"}
            description={area && log.hasNextPage ? "Older changes may still be further back." : "Changes made in the console show up here."}
          />
        ) : (
          <ol>
            {shown.map((entry) => (
              <AuditRow key={entry.id} entry={entry} now={now} modelNames={modelNames} />
            ))}
          </ol>
        )}
        {log.hasNextPage ? (
          <div className="border-t py-3 text-center">
            <Button variant="outline" size="sm" disabled={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
              {log.isFetchingNextPage ? "Loading…" : "Show more"}
            </Button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
