import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { ConsoleApi, consoleApi } from "@/lib/console-api";
import type { AuditEntry, ConsoleLearner, LearnerPage, Page } from "@/lib/types";

/** The cache entries of the Learners and Change log pages. They are in their own class so that each page's queries sit
 *  next to its data shaping (`lib/console-people.ts`, `lib/console-audit.ts`); the keys start with "console" like every other. */
export class PeopleQueries {
  static readonly LEARNERS_PAGE = 25;
  /** The newest learners the tiles are worked out from: "new this week" and "most common" need rows, the counts do not. */
  static readonly SAMPLE_SIZE = 100;
  static readonly AUDIT_PAGE = 50;

  constructor(private readonly api: ConsoleApi = consoleApi) {}

  /** Learners matching the search, a page at a time (newest first). */
  learners(search: string) {
    const q = search.trim();
    return infiniteQueryOptions({
      queryKey: ["console", "learners", "list", q] as const,
      queryFn: ({ pageParam }): Promise<LearnerPage> => this.api.learners({ q, cursor: pageParam, pageSize: PeopleQueries.LEARNERS_PAGE }),
      initialPageParam: null as string | null,
      getNextPageParam: (last: Page<ConsoleLearner>) => ConsoleApi.cursorOf(last.next) ?? undefined,
    });
  }

  /** The summary and the newest learners for the tiles: the same whatever is searched. */
  learnerSample() {
    return queryOptions({
      queryKey: ["console", "learners", "sample"] as const,
      queryFn: (): Promise<LearnerPage> => this.api.learners({ pageSize: PeopleQueries.SAMPLE_SIZE }),
    });
  }

  /** The change log, newest first, a page at a time. */
  audit() {
    return infiniteQueryOptions({
      queryKey: ["console", "audit"] as const,
      queryFn: ({ pageParam }): Promise<Page<AuditEntry>> => this.api.audit({ cursor: pageParam, pageSize: PeopleQueries.AUDIT_PAGE }),
      initialPageParam: null as string | null,
      getNextPageParam: (last: Page<AuditEntry>) => ConsoleApi.cursorOf(last.next) ?? undefined,
    });
  }
}

export const peopleQueries = new PeopleQueries();
