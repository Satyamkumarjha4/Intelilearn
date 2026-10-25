"use client";

import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { SearchIcon, UsersIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { EmptyState } from "@/components/console/empty-state";
import { ErrorState } from "@/components/console/error-state";
import { KpiTile } from "@/components/console/kpi-tile";
import { PageHeader } from "@/components/console/page-header";
import { LearnersTable } from "@/components/console/people/learners-table";
import { KpiRowSkeleton } from "@/components/console/skeletons";
import { notFoundIfRefused } from "@/components/console/not-found-guard";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { useDebouncedText } from "@/components/console/use-debounced-text";
import { useNow } from "@/components/lessons/use-now";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { LearnerStats, PeopleUrl } from "@/lib/console-people";
import { peopleQueries } from "@/lib/console-people-queries";

/** The Learners page: who is using Socra. Read-only; the search lives in the address. */
export function LearnersView() {
  const router = useRouter();
  const pathname = usePathname();
  const q = PeopleUrl.search(useSearchParams());
  const [text, setText] = useDebouncedText(q, (next) => router.replace(`${pathname}${PeopleUrl.searchQuery(next)}`, { scroll: false }));
  const now = new Date(useNow(true, 60_000));

  const sample = useConsoleQuery(peopleQueries.learnerSample());
  const list = notFoundIfRefused(useInfiniteQuery({ ...peopleQueries.learners(q), placeholderData: keepPreviousData }));
  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.results) ?? [], [list.data]);

  const tiles = sample.data
    ? LearnerStats.tiles(sample.data.summary, { rows: sample.data.results, more: sample.data.next !== null }, now)
    : null;

  return (
    <div>
      <PageHeader
        title="Learners"
        description="Who is using Socra. Read-only here; account changes stay in the Django admin."
        actions={
          <label className="flex min-w-0 items-center gap-1.5 rounded-[10px] border bg-card px-2.5 py-1.5 text-muted-foreground focus-within:ring-3 focus-within:ring-ring/50 sm:w-64">
            <SearchIcon className="size-[15px] shrink-0" aria-hidden="true" />
            <input
              type="search"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Name or email"
              aria-label="Search learners"
              className="min-w-0 flex-1 bg-transparent font-semibold text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>
        }
      />

      <div className="mb-4">
        {tiles ? (
          <div className="grid grid-cols-4 gap-4 max-[1180px]:grid-cols-2 max-[560px]:grid-cols-1">
            {tiles.map((tile) => (
              <KpiTile key={tile.key} data={tile} />
            ))}
          </div>
        ) : sample.error ? null : (
          <KpiRowSkeleton />
        )}
      </div>

      <section aria-label="Learners" aria-busy={list.isFetching && !list.isFetchingNextPage} className="min-w-0 rounded-2xl border bg-card shadow-card">
        <div className="px-[18px] py-3">
          {list.error && !list.data ? (
            <ErrorState message="The learners could not be loaded." onRetry={() => void list.refetch()} />
          ) : list.isPending ? (
            <div role="status" aria-label="Loading learners" className="grid gap-2">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-11 w-full" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState icon={UsersIcon} title={q ? `No learners match “${q}”` : "No learners yet"} description={q ? "Try part of a name or an email address." : "Accounts show up here as people sign up."} />
          ) : (
            <>
              <LearnersTable rows={rows} now={now} />
              <p className="mt-2 text-[12.5px] font-semibold text-muted-foreground">
                {q ? `${rows.length} ${rows.length === 1 ? "match" : "matches"} loaded` : `${rows.length} loaded`}
                {list.hasNextPage ? ", newest first" : ""}
              </p>
            </>
          )}
          {list.hasNextPage ? (
            <div className="mt-3 text-center">
              <Button variant="outline" size="sm" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
                {list.isFetchingNextPage ? "Loading…" : "Show more"}
              </Button>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
