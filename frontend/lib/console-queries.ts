import { QueryClient, queryOptions } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { consoleApi, type ConsoleApi } from "@/lib/console-api";
import type { ConsoleFlowSettings, ConsoleModel, ConsoleProvider, ConsoleRange, ConsoleRouting, RoutingProfile, RunRow, UsageFilters } from "@/lib/types";

const HOUR_MS = 3_600_000;

/** Failed runs of the last day: the sidebar's badge. A run has no "failed at", so a run counts by when it was created. */
export class FailedRuns {
  static countWithin(rows: readonly Pick<RunRow, "created_at">[], now: number, hours = 24): number {
    return rows.filter((row) => now - Date.parse(row.created_at) <= hours * HOUR_MS).length;
  }
}

export class ConsoleErrors {
  /** The console answers anyone who may not use it with a 404 (and a screen that is not there is one too). */
  static isNotFound(error: unknown): boolean {
    return error instanceof ApiError && error.status === 404;
  }

  /** Whether to try a failed request again: not when the answer is a refusal that asking again cannot change. */
  static shouldRetry(failureCount: number, error: unknown): boolean {
    if (error instanceof ApiError && [400, 401, 403, 404].includes(error.status)) return false;
    return failureCount < 2;
  }
}

/**
 * The console pages' queries (TanStack Query): what each is called, how to fetch it, how long it stays fresh. The keys
 * start with "console", so everything the console cached can be cleared or refetched together, and they carry the
 * filters, so a filter change is a different entry (and going back to one is instant).
 */
export class ConsoleQueries {
  /** The overview is polled this often while its tab is visible, so health and attention stay current. */
  static readonly POLL_MS = 60_000;
  /** Lists that change by hand (providers, models, step names) are fresh this long. */
  static readonly LIST_STALE_MS = 5 * 60_000;

  constructor(
    private readonly api: ConsoleApi = consoleApi,
    private readonly now: () => number = () => Date.now(),
  ) {}

  overview(range: ConsoleRange) {
    return queryOptions({
      queryKey: ["console", "overview", range] as const,
      queryFn: () => this.api.overview(range),
      refetchInterval: ConsoleQueries.POLL_MS,
    });
  }

  usage(filters: UsageFilters) {
    return queryOptions({
      queryKey: ["console", "usage", ConsoleQueries.clean(filters)] as const,
      queryFn: () => this.api.usage(filters),
    });
  }

  providers() {
    return queryOptions({
      queryKey: ["console", "providers"] as const,
      queryFn: async (): Promise<ConsoleProvider[]> => (await this.api.providers({ pageSize: 100 })).results,
      staleTime: ConsoleQueries.LIST_STALE_MS,
    });
  }

  models() {
    return queryOptions({
      queryKey: ["console", "models"] as const,
      queryFn: async (): Promise<ConsoleModel[]> => (await this.api.models({ pageSize: 100 })).results,
      staleTime: ConsoleQueries.LIST_STALE_MS,
    });
  }

  /** The keys of the lesson steps, in lesson order (for the usage page's step filter). */
  steps() {
    return queryOptions({
      queryKey: ["console", "steps"] as const,
      queryFn: async (): Promise<string[]> => (await this.api.routing()).phases.flatMap((phase) => phase.nodes.map((node) => node.key)),
      staleTime: ConsoleQueries.LIST_STALE_MS,
    });
  }

  /**
   * Every step with its settings and chain. Not refetched when the tab regains focus: the page keeps unsaved edits
   * beside this copy, and a copy that shifted under them would change what "unsaved" means.
   */
  routing() {
    return queryOptions({
      queryKey: ["console", "routing"] as const,
      queryFn: (): Promise<ConsoleRouting> => this.api.routing(),
      refetchOnWindowFocus: false,
    });
  }

  profiles() {
    return queryOptions({
      queryKey: ["console", "profiles"] as const,
      queryFn: (): Promise<RoutingProfile[]> => this.api.profiles(),
      staleTime: ConsoleQueries.LIST_STALE_MS,
    });
  }

  /** The lesson settings, with the same rule about focus as `routing`. */
  flowSettings() {
    return queryOptions({
      queryKey: ["console", "flow-settings"] as const,
      queryFn: (): Promise<ConsoleFlowSettings> => this.api.flowSettings(),
      refetchOnWindowFocus: false,
    });
  }

  /** How many runs failed in the last 24 hours (the newest 100 runs that failed are looked at). */
  failedRuns() {
    return queryOptions({
      queryKey: ["console", "failed-runs"] as const,
      queryFn: async (): Promise<number> => {
        const page = await this.api.runs({ status: "failed", pageSize: 100 });
        return FailedRuns.countWithin(page.results, this.now());
      },
      refetchInterval: ConsoleQueries.POLL_MS,
    });
  }

  /** The filters without the empty ones, so `{provider: ""}` and `{}` are the same cache entry. */
  private static clean(filters: UsageFilters): UsageFilters {
    return Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) as UsageFilters;
  }
}

export const consoleQueries = new ConsoleQueries();

/** The query client of one visit to the console: it refetches when the tab regains focus, and does not ask again after a refusal. */
export class ConsoleQueryClient {
  /** Data this recent is shown without asking again (a filter change back to a seen view is instant). */
  static readonly STALE_MS = 30_000;

  static create(): QueryClient {
    return new QueryClient({
      defaultOptions: {
        queries: { retry: ConsoleErrors.shouldRetry, refetchOnWindowFocus: true, staleTime: ConsoleQueryClient.STALE_MS },
      },
    });
  }
}
