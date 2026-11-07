/** The shapes of the console's credit, wallet, payment and revenue endpoints (docs/reference/api.md, "Console"). */

export type PriceHistoryRow = { credits: number; label: string; active: boolean; updated_by: string; updated_at: string };
export type ConsolePrice = {
  key: string;
  label: string;
  /** The live price; null when the key has none (then it is unavailable, never free). */
  credits: number | null;
  available: boolean;
  updated_by: string;
  updated_at: string;
  history: PriceHistoryRow[];
};
export type ConsolePlan = {
  key: string;
  name: string;
  credits: number;
  period_days: number;
  price_paise: number;
  max_quantity: number;
  active: boolean;
  sort: number;
};
/** Amounts and windows of the credit rules: whole numbers, with no other kind of field. */
export type ConsoleCreditSettings = Record<string, number>;
export type CreditsConfig = { prices: ConsolePrice[]; plans: ConsolePlan[]; settings: ConsoleCreditSettings };

export type WalletBucket = {
  id: string;
  source: string;
  remaining: number;
  granted: number;
  expires_at: string | null;
  lapsed: boolean;
  created_at: string;
};
export type LedgerRow = { id: number; type: string; amount: number; balance_after: number; action: string; reason: string; created_at: string };
export type WalletPanel = {
  learner: { id: string; name: string; email: string };
  balance: number;
  reserved: number;
  credits_exempt: boolean;
  buckets: WalletBucket[];
  transactions: LedgerRow[];
};

export type RefundRow = {
  id: number;
  amount_paise: number;
  refund_ref: string;
  state: "pending" | "confirmed" | "failed";
  created_at: string;
  resolved_at: string | null;
  can_mark_failed: boolean;
};
export type PaymentStatus = "created" | "pending" | "paid" | "fulfilled" | "failed" | "expired";
export type PaymentRow = {
  id: string;
  learner: { id: string; name: string; email: string };
  gateway: string;
  plan: string;
  amount_paise: number;
  refunded_paise: number;
  currency: string;
  status: PaymentStatus;
  provider_ref: string;
  payment_ref: string;
  created_at: string;
  paid_at: string | null;
  shortfall_credits: number;
  refunds: RefundRow[];
};
export type PaymentsSummary = { shortfalls: number; refunds_waiting: number; orders_waiting: number };
export type PaymentPage = { next: string | null; previous: string | null; results: PaymentRow[]; summary: PaymentsSummary };
export type Shortfall = {
  id: number;
  order: string | null;
  learner: { email: string; name: string } | null;
  gateway: string;
  kind: string;
  amount_paise: number;
  shortfall_credits: number;
  received_at: string;
};
export type RefundResult = { kind: "asked" | "duplicate"; amount_paise: number; message: string; order: PaymentRow };
export type PaymentFilters = { status?: string; gateway?: string; q?: string };

export type Revenue = {
  range: string;
  period: { start: string; end: string };
  orders: number;
  paid: string;
  refunded: string;
  net: string;
  model_cost_usd: string;
  model_cost: string;
  after_model_cost: string;
  usd_inr_rate: string;
};
