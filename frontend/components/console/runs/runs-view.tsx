"use client";

import { RefreshCwIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { RunDetailPanel } from "@/components/console/runs/run-detail-panel";
import { RunFilterBar } from "@/components/console/runs/run-filter-bar";
import { RunsTable } from "@/components/console/runs/runs-table";
import { useRunDetail } from "@/components/console/runs/use-run-detail";
import { useRuns } from "@/components/console/runs/use-runs";
import { useNow } from "@/components/lessons/use-now";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { RunFilters, type RunFilterState } from "@/lib/run-filters";

const SEARCH_PAUSE_MS = 300;
/** Where the detail moves from under the table to beside it. */
const WIDE = "(min-width: 1180px)";

/** The Lesson runs page. Filters and the open run live in the address; the table and the detail read from it. */
export function RunsView() {
  const router = useRouter();
  const pathname = usePathname();
  const filters = RunFilters.parse(useSearchParams());
  const { rows, hasMore, error, loadingMore, failed, loadMore, refresh } = useRuns(filters);
  const { detail, error: detailError, reload } = useRunDetail(filters.run, () => void refresh());
  const now = new Date(useNow(true, 30_000));
  const detailRef = useRef<HTMLDivElement>(null);

  const go = (patch: Partial<RunFilterState>) =>
    router.replace(RunFilters.href(pathname, RunFilters.change(filters, patch)), { scroll: false });

  // The search box runs ahead of the address while typing, and follows it when it changes by itself (back, a link).
  const [search, setSearch] = useState(filters.q);
  const committed = useRef(filters.q);
  useEffect(() => {
    if (filters.q !== committed.current) {
      committed.current = filters.q;
      setSearch(filters.q);
    }
  }, [filters.q]);
  const typeSearch = (text: string) => {
    setSearch(text);
    const run = RunFilters.runIdIn(text);
    if (run) {
      committed.current = "";
      setSearch("");
      go({ q: "", run });
    }
  };
  useEffect(() => {
    if (search.trim() === committed.current.trim() || RunFilters.runIdIn(search)) return;
    const timer = setTimeout(() => {
      committed.current = search;
      go({ q: search });
    }, SEARCH_PAUSE_MS);
    return () => clearTimeout(timer);
    // `go` is rebuilt on every render; the pause restarts only when the typing changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const open = (id: string) => {
    go({ run: id });
    // Under the table the detail is off screen, so bring it into view.
    if (!window.matchMedia(WIDE).matches) requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: "start" }));
  };
  const changed = (openRun: string | null) => {
    if (openRun) go({ run: openRun });
    else void reload();
    void refresh();
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px]">Lesson runs</h1>
          <p className="mt-1 text-muted-foreground">Every lesson build, quiz resume, repair and grading job.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void refresh()} aria-label="Refresh the list">
          <RefreshCwIcon /> Refresh
        </Button>
      </div>

      <RunFilterBar
        filters={filters}
        search={search}
        failed={failed}
        onStatus={(status) => go({ status })}
        onJob={(job) => go({ job })}
        onSearch={typeSearch}
      />

      <div className="grid items-start gap-4 min-[1180px]:grid-cols-[minmax(0,1fr)_440px]">
        <Card className="min-w-0 gap-0 p-0">
          {error && (
            <Alert variant="destructive" className="m-3 w-auto">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {rows === null && !error && (
            <div className="grid gap-2 p-3" aria-busy="true" aria-label="Loading runs">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          )}
          {rows && rows.length === 0 && (
            <p className="p-8 text-center text-muted-foreground">
              {filters.q || filters.job || filters.status !== "all" ? "No runs match these filters." : "No runs yet."}
            </p>
          )}
          {rows && rows.length > 0 && <RunsTable rows={rows} selected={filters.run} onOpen={open} now={now} />}
          {hasMore && (
            <div className="border-t p-3 text-center">
              <Button variant="outline" size="sm" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore ? "Loading…" : "Show more runs"}
              </Button>
            </div>
          )}
        </Card>

        <div ref={detailRef} className="min-w-0 scroll-mt-4 min-[1180px]:sticky min-[1180px]:top-4 min-[1180px]:max-h-[calc(100vh-2rem)] min-[1180px]:overflow-y-auto">
          <RunDetailPanel id={filters.run} detail={detail} error={detailError} onChanged={changed} now={now} />
        </div>
      </div>
    </div>
  );
}
