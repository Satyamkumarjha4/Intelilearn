"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { ConsoleApi, consoleApi } from "@/lib/console-api";
import { RunFilters, type RunFilterState } from "@/lib/run-filters";
import type { Page, RunRow } from "@/lib/types";

const FAILED_PAGE = 100;

type Listing = { key: string; rows: RunRow[]; next: string | null };

/**
 * The run list for the filters in the address: the first page, "show more", and how many runs failed (for the Failed
 * tab, whichever tab is open). A listing is kept with the filters it was fetched for, so the rows of an earlier
 * filter are never shown under a later one, and a late reply for earlier filters is dropped.
 */
export function useRuns(filters: RunFilterState) {
  const { status, job, q } = filters;
  const key = `${status}|${job}|${q.trim()}`;
  const [listing, setListing] = useState<Listing | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [failed, setFailed] = useState<{ count: number; more: boolean } | null>(null);
  // Bumped to ask for the list and the count again.
  const [round, setRound] = useState(0);

  useEffect(() => {
    let active = true;
    consoleApi
      .runs(RunFilters.query({ status, job, q, run: null }))
      .then((page) => {
        if (!active) return;
        setListing({ key, rows: page.results, next: ConsoleApi.cursorOf(page.next) });
        setFailure(null);
      })
      .catch((err) => active && setFailure({ key, message: err instanceof ApiError ? err.message : "We couldn't load the runs." }));
    return () => {
      active = false;
    };
  }, [key, status, job, q, round]);

  useEffect(() => {
    let active = true;
    consoleApi
      .runs({ status: "failed", pageSize: FAILED_PAGE })
      .then((page: Page<RunRow>) => active && setFailed({ count: page.results.length, more: page.next !== null }))
      .catch(() => undefined); // the count is a nicety: the tab still works without it
    return () => {
      active = false;
    };
  }, [round]);

  const current = listing && listing.key === key ? listing : null;

  const loadMore = async () => {
    if (!current?.next) return;
    setLoadingMore(true);
    try {
      const page = await consoleApi.runs({ ...RunFilters.query({ status, job, q, run: null }), cursor: current.next });
      setListing((now) =>
        now && now.key === key ? { key, rows: [...now.rows, ...page.results], next: ConsoleApi.cursorOf(page.next) } : now,
      );
    } catch (err) {
      setFailure({ key, message: err instanceof ApiError ? err.message : "We couldn't load more runs." });
    } finally {
      setLoadingMore(false);
    }
  };

  return {
    rows: current?.rows ?? null,
    hasMore: Boolean(current?.next),
    error: failure && failure.key === key ? failure.message : null,
    loadingMore,
    failed,
    loadMore,
    refresh: () => setRound((n) => n + 1),
  };
}
