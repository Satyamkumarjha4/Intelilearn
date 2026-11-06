import { apiClient, type ApiClient } from "@/lib/api";
import type { Page } from "@/lib/types";
import type { Balance, Notice, Plans, Quote, Repaired, Streak, Transaction, Wallet } from "./types";

/** The credits endpoints (docs/reference/api.md, "Credits"), typed. */
export class CreditsApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  wallet(): Promise<Wallet> {
    return this.client.request("/credits/wallet");
  }

  balance(): Promise<Balance> {
    return this.client.request("/credits/balance");
  }

  notices(): Promise<{ notices: Notice[] }> {
    return this.client.request("/credits/notices");
  }

  quote(action: string, size: Record<string, unknown>): Promise<Quote> {
    return this.client.request("/credits/quote", { method: "POST", body: { action, size } });
  }

  /** What Retry on a failed lesson would ask for now: the same price again, or nothing when its work was kept. */
  retryQuote(lessonId: string): Promise<Quote> {
    return this.client.request(`/credits/retry-quote?lesson=${encodeURIComponent(lessonId)}`);
  }

  transactions(cursor?: string | null): Promise<Page<Transaction>> {
    return this.client.request(`/credits/transactions${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`);
  }

  streak(): Promise<Streak> {
    return this.client.request("/credits/streak");
  }

  repair(): Promise<Repaired> {
    return this.client.request("/credits/streak/repair", { method: "POST" });
  }

  plans(): Promise<Plans> {
    return this.client.request("/credits/plans");
  }
}

export const creditsApi = new CreditsApi();
