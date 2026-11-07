import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { ConsoleApi, consoleApi } from "@/lib/console-api";
import type { UsageFilters } from "@/lib/types";

import type { CreditsConfig, PaymentFilters, PaymentPage, Revenue, Shortfall, WalletPanel } from "./types";

/** The cache entries of the credit, wallet, payment and revenue screens. Their keys start with "console" like every other. */
export class CreditQueries {
  static readonly PAYMENTS_PAGE = 25;

  constructor(private readonly api: ConsoleApi = consoleApi) {}

  /** Prices, plans and settings: not refetched when the tab regains focus, so an edit in progress is not replaced. */
  config() {
    return queryOptions({
      queryKey: ["console", "credits"] as const,
      queryFn: (): Promise<CreditsConfig> => this.api.credits(),
      refetchOnWindowFocus: false,
    });
  }

  wallet(learnerId: string) {
    return queryOptions({
      queryKey: ["console", "wallet", learnerId] as const,
      queryFn: (): Promise<WalletPanel> => this.api.wallet(learnerId),
    });
  }

  payments(filters: PaymentFilters) {
    const clean = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
    return infiniteQueryOptions({
      queryKey: ["console", "payments", "list", clean] as const,
      queryFn: ({ pageParam }): Promise<PaymentPage> => this.api.payments({ ...filters, cursor: pageParam, pageSize: CreditQueries.PAYMENTS_PAGE }),
      initialPageParam: null as string | null,
      getNextPageParam: (last: PaymentPage) => ConsoleApi.cursorOf(last.next) ?? undefined,
    });
  }

  shortfalls() {
    return queryOptions({
      queryKey: ["console", "payments", "shortfalls"] as const,
      queryFn: (): Promise<Shortfall[]> => this.api.shortfalls(),
    });
  }

  revenue(filters: UsageFilters) {
    const { range, start, end } = filters;
    return queryOptions({
      queryKey: ["console", "revenue", { range, start, end }] as const,
      queryFn: (): Promise<Revenue> => this.api.revenue(filters),
    });
  }
}

export const creditQueries = new CreditQueries();
