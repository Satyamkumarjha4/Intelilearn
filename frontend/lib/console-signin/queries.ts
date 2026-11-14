import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { ConsoleApi, consoleApi } from "@/lib/console-api";

import type { AbuseReport, PendingSignupPage, VerificationPanel } from "./types";

/** The cache entries of the sign-in screens. Their keys start with "console" like every other, so one invalidation
 *  after an action refreshes them all. */
export class SigninQueries {
  static readonly SIGNUPS_PAGE = 25;

  constructor(private readonly api: ConsoleApi = consoleApi) {}

  verification(learnerId: string) {
    return queryOptions({
      queryKey: ["console", "verification", learnerId] as const,
      queryFn: (): Promise<VerificationPanel> => this.api.verification(learnerId),
    });
  }

  signups(search: string) {
    const q = search.trim();
    return infiniteQueryOptions({
      queryKey: ["console", "signups", q] as const,
      queryFn: ({ pageParam }): Promise<PendingSignupPage> => this.api.signups({ q, cursor: pageParam, pageSize: SigninQueries.SIGNUPS_PAGE }),
      initialPageParam: null as string | null,
      getNextPageParam: (last: PendingSignupPage) => ConsoleApi.cursorOf(last.next) ?? undefined,
    });
  }

  abuse() {
    return queryOptions({
      queryKey: ["console", "abuse"] as const,
      queryFn: (): Promise<AbuseReport> => this.api.abuse(),
      refetchInterval: 60_000,
    });
  }
}

export const signinQueries = new SigninQueries();
