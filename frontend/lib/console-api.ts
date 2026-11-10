import { ApiError, apiClient, type ApiClient } from "@/lib/api";
import type {
  AuditEntry,
  ConsoleFlowSettings,
  ConsoleModel,
  ConsoleOverview,
  ConsoleProvider,
  ConsoleRange,
  ConsoleRouting,
  ConsoleUsage,
  FlowSettingsValues,
  LearnerPage,
  ModelChanges,
  NewModel,
  NodeRouting,
  NodeRoutingInput,
  Page,
  ProbeResult,
  ProfilePreview,
  ProviderChanges,
  RoutingProfile,
  RunDetail,
  RunQuery,
  RunRow,
  RunStatus,
  UsageFilters,
} from "@/lib/types";

import type {
  ConsoleCreditSettings,
  ConsolePlan,
  ConsolePrice,
  CreditsConfig,
  ErasurePreview,
  ErasureResult,
  PaymentFilters,
  PaymentPage,
  RefundResult,
  RefundRow,
  Revenue,
  Shortfall,
  WalletPanel,
} from "@/lib/console-credits/types";
import type { ConsoleTestimonial, TestimonialInput, TestimonialList } from "@/lib/console-testimonials/types";

export type PageQuery = { cursor?: string | null; pageSize?: number };

/**
 * The staff-only console endpoints (docs/reference/api.md, "Console"), typed.
 *
 * The console answers anyone who is not signed in as staff with a 404, so that it does not announce itself. That also
 * means a staff member whose access cookie has just expired looks like a stranger and gets a 404 instead of the 401
 * that makes `ApiClient` refresh the session. So a 404 is retried once after a refresh (at most one refresh a minute,
 * so a run that really does not exist does not renew the session on every look).
 */
export class ConsoleApi {
  private lastRefresh = Number.NEGATIVE_INFINITY;

  constructor(
    private readonly client: ApiClient = apiClient,
    private readonly now: () => number = () => Date.now(),
  ) {}

  // --- overview and usage

  overview(range?: ConsoleRange): Promise<ConsoleOverview> {
    return this.get(`/console/overview${ConsoleApi.query({ range })}`);
  }

  usage(filters: UsageFilters = {}): Promise<ConsoleUsage> {
    return this.get(`/console/usage${ConsoleApi.query(filters)}`);
  }

  /** Where the CSV of the same filtered calls is downloaded (a link for the browser, not an API call). */
  usageExportUrl(filters: UsageFilters = {}): string {
    return `/api/console/usage/export.csv${ConsoleApi.query(filters)}`;
  }

  // --- runs

  runs(query: RunQuery & PageQuery = {}): Promise<Page<RunRow>> {
    const { status, graph, q, ...page } = query;
    const filters = { status: ConsoleApi.list(status), graph: ConsoleApi.list(graph), q: q?.trim() };
    const params = { ...filters, ...ConsoleApi.page(page) };
    return this.get(`/console/runs${ConsoleApi.query(params)}`);
  }

  run(id: string): Promise<RunDetail> {
    return this.get(`/console/runs/${id}`);
  }

  /** The learner's Retry, as staff: a new run for a failed lesson. */
  retryRun(id: string): Promise<{ run_id: string; lesson_id: string }> {
    return this.send("POST", `/console/runs/${id}/retry`);
  }

  cancelRun(id: string): Promise<{ id: string; status: RunStatus }> {
    return this.send("POST", `/console/runs/${id}/cancel`);
  }

  // --- providers and models

  providers(page: PageQuery = {}): Promise<Page<ConsoleProvider>> {
    return this.get(`/console/providers${ConsoleApi.query(ConsoleApi.page(page))}`);
  }

  updateProvider(key: string, changes: ProviderChanges): Promise<ConsoleProvider> {
    return this.send("PATCH", `/console/providers/${key}`, changes);
  }

  models(page: PageQuery = {}): Promise<Page<ConsoleModel>> {
    return this.get(`/console/models${ConsoleApi.query(ConsoleApi.page(page))}`);
  }

  addModel(model: NewModel): Promise<ConsoleModel> {
    return this.send("POST", "/console/models", model);
  }

  updateModel(id: number, changes: ModelChanges): Promise<ConsoleModel> {
    return this.send("PATCH", `/console/models/${id}`, changes);
  }

  /** Refused with a 409 `model_in_use` (the steps in `error.extra.nodes`) while a step has the model bound. */
  deleteModel(id: number): Promise<void> {
    return this.send("DELETE", `/console/models/${id}`);
  }

  /** Makes real calls to the provider, for up to 20 seconds. Always resolves: a failing model is `ok: false`. */
  probeModel(id: number): Promise<ProbeResult> {
    return this.send("POST", `/console/models/${id}/probe`);
  }

  // --- routing

  routing(): Promise<ConsoleRouting> {
    return this.get("/console/nodes");
  }

  /** Replaces the step's settings and its whole chain at once. */
  saveNode(key: string, routing: NodeRoutingInput): Promise<NodeRouting> {
    return this.send("PUT", `/console/nodes/${key}`, routing);
  }

  profiles(): Promise<RoutingProfile[]> {
    return this.get("/console/profiles");
  }

  /** What the profile would change, step by step. Saves nothing. */
  previewProfile(name: string): Promise<ProfilePreview> {
    return this.send("POST", `/console/profiles/${name}/preview`);
  }

  // --- settings, learners, change log

  flowSettings(): Promise<ConsoleFlowSettings> {
    return this.get("/console/flow-settings");
  }

  updateFlowSettings(changes: Partial<FlowSettingsValues>): Promise<ConsoleFlowSettings> {
    return this.send("PATCH", "/console/flow-settings", changes);
  }

  learners(query: { q?: string } & PageQuery = {}): Promise<LearnerPage> {
    return this.get(`/console/learners${ConsoleApi.query({ q: query.q?.trim(), ...ConsoleApi.page(query) })}`);
  }

  audit(page: PageQuery = {}): Promise<Page<AuditEntry>> {
    return this.get(`/console/audit${ConsoleApi.query(ConsoleApi.page(page))}`);
  }

  // --- testimonials

  testimonials(): Promise<TestimonialList> {
    return this.get("/console/testimonials");
  }

  addTestimonial(body: TestimonialInput): Promise<ConsoleTestimonial> {
    return this.send("POST", "/console/testimonials", body);
  }

  /** Any subset of the fields; publishing is `is_published`. A 400 names the field and says why (no consent, a sample). */
  updateTestimonial(id: number, changes: Partial<TestimonialInput>): Promise<ConsoleTestimonial> {
    return this.send("PATCH", `/console/testimonials/${id}`, changes);
  }

  deleteTestimonial(id: number): Promise<void> {
    return this.send("DELETE", `/console/testimonials/${id}`);
  }

  /** `ids` must be every testimonial's id exactly once, in the new order. */
  reorderTestimonials(ids: number[]): Promise<TestimonialList> {
    return this.send("POST", "/console/testimonials/reorder", { ids });
  }

  // --- credits, wallets, payments, revenue

  credits(): Promise<CreditsConfig> {
    return this.get("/console/credits");
  }

  /** Makes `credits` the live price of `key` (an edit adds a row; the old price stays in the history). */
  revisePrice(key: string, body: { credits: number; label?: string }): Promise<ConsolePrice> {
    return this.send("PATCH", `/console/credits/prices/${encodeURIComponent(key)}`, body);
  }

  updatePlan(key: string, changes: Partial<Omit<ConsolePlan, "key">>): Promise<ConsolePlan> {
    return this.send("PATCH", `/console/credits/plans/${encodeURIComponent(key)}`, changes);
  }

  updateCreditSettings(changes: Partial<ConsoleCreditSettings>): Promise<ConsoleCreditSettings> {
    return this.send("PATCH", "/console/credits/settings", changes);
  }

  wallet(learnerId: string): Promise<WalletPanel> {
    return this.get(`/console/learners/${learnerId}/wallet`);
  }

  /** The reason is required; `token` makes sending the same form twice move the credits once. */
  adjustWallet(learnerId: string, body: { amount: number; reason: string; token: string }): Promise<WalletPanel> {
    return this.send("POST", `/console/learners/${learnerId}/wallet/adjust`, body);
  }

  setExempt(learnerId: string, creditsExempt: boolean): Promise<WalletPanel> {
    return this.send("PATCH", `/console/learners/${learnerId}/wallet`, { credits_exempt: creditsExempt });
  }

  /** What erasing the learner would delete and keep, and whether it is allowed. Writes nothing. */
  erasurePreview(learnerId: string): Promise<ErasurePreview> {
    return this.get(`/console/learners/${learnerId}/erasure`);
  }

  /** Deletes the learner's data for good. `confirmEmail` must be the account's own email. A 409 `code` says why not
   *  (`cannot_erase_self`, `staff_account`, `already_erased`); a 400 names `confirm_email`. */
  eraseLearner(learnerId: string, confirmEmail: string): Promise<ErasureResult> {
    return this.send("DELETE", `/console/learners/${learnerId}/erasure`, { confirm_email: confirmEmail });
  }

  payments(filters: PaymentFilters & PageQuery = {}): Promise<PaymentPage> {
    const { status, gateway, q, ...page } = filters;
    return this.get(`/console/payments${ConsoleApi.query({ status, gateway, q: q?.trim(), ...ConsoleApi.page(page) })}`);
  }

  shortfalls(): Promise<Shortfall[]> {
    return this.get("/console/payments/shortfalls");
  }

  /** Refused with a 409 whose `code` says why (`too_much`, `all_asked`, `in_full`, `not_fulfilled`, `dashboard`, `failed`). */
  refund(orderId: string, body: { token: string; amount?: string }): Promise<RefundResult> {
    return this.send("POST", `/console/payments/${orderId}/refund`, body);
  }

  markRefundFailed(attemptId: number): Promise<RefundRow> {
    return this.send("POST", `/console/refunds/${attemptId}/mark-failed`);
  }

  revenue(filters: UsageFilters = {}): Promise<Revenue> {
    return this.get(`/console/revenue${ConsoleApi.query({ range: filters.range, start: filters.start, end: filters.end })}`);
  }

  /** The cursor inside a `next` link from a list reply (the link itself points at the backend's own host). */
  static cursorOf(next: string | null): string | null {
    if (!next) return null;
    return new URL(next, "http://placeholder").searchParams.get("cursor");
  }

  // --- plumbing

  private get<T>(path: string): Promise<T> {
    return this.send("GET", path);
  }

  private async send<T>(method: string, path: string, body?: unknown): Promise<T> {
    const options = { method, ...(body === undefined ? {} : { body }) };
    try {
      return await this.client.request<T>(path, options);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404 || !(await this.refreshedRecently())) throw error;
      return this.client.request<T>(path, options); // a 404 from the console means the request did nothing
    }
  }

  /** Refresh the session unless that was done within the last minute; true if the session was renewed. */
  private async refreshedRecently(): Promise<boolean> {
    if (this.now() - this.lastRefresh < 60_000) return false;
    this.lastRefresh = this.now();
    return this.client.refreshSession();
  }

  private static list<T extends string>(value: T | T[] | "" | undefined): string | undefined {
    const values = [value ?? []].flat().filter(Boolean);
    return values.length ? values.join(",") : undefined;
  }

  private static page(page: PageQuery): Record<string, string | number | null | undefined> {
    return { cursor: page.cursor, page_size: page.pageSize };
  }

  /** `?a=1&b=2` from the given values, leaving out the empty ones; "" when there are none. */
  private static query(params: Record<string, string | number | null | undefined>): string {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
    }
    const text = search.toString();
    return text ? `?${text}` : "";
  }
}

export const consoleApi = new ConsoleApi();
