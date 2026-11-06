/** The shapes of the credits endpoints (docs/reference/api.md, "Credits"). */

export type PriceLine = { key: string; label: string; credits: number };

/** What an action costs (`POST /credits/quote`). `later` is what follows a Quick check; `exempt` means the learner is not charged. */
export type Quote = {
  action: string;
  lines: PriceLine[];
  due_now: number;
  later_lines: PriceLine[];
  later: number;
  total: number;
  exempt: boolean;
};

export type WalletBucket = { source: string; remaining: number; expires_at: string | null };

export type Wallet = {
  balance: number;
  held: number;
  buckets: WalletBucket[];
  next_expiry: { at: string; credits: number } | null;
  exempt: boolean;
};

/** The light answer for the header (`GET /credits/balance`). */
export type Balance = { balance: number; reserved: number; notices: number };

/** Credits about to run out (`GET /credits/notices`). `id` is one per day they run out, so a browser can hide it for the day. */
export type Notice = { id: string; expires_on: string; days_left: number; credits: number; text: string };

export type TransactionKind = "earned" | "bought" | "reserved" | "used" | "returned" | "expired" | "adjusted" | "taken_back";

export type Transaction = {
  id: number;
  kind: TransactionKind;
  text: string;
  amount: number;
  balance_after: number;
  created_at: string;
  subject: { kind: "lesson" | "quiz"; id: string; title: string } | null;
};

export type StreakDayState = "active" | "repaired" | "missed" | "pending";

export type RepairOutlook = {
  available: boolean;
  day: string | null;
  reason: "nothing_to_repair" | "repair_limit" | null;
  cost: number;
  left_week: number;
  left_month: number;
};

export type Streak = {
  current: number;
  longest: number;
  run_started_on: string | null;
  alive: boolean;
  zone: string;
  today: { date: string; done: boolean };
  days: { date: string; state: StreakDayState }[];
  next_bonus: { streak_day: number; credits: number; days_to_go: number };
  repair: RepairOutlook;
};

export type Repaired = {
  day: string;
  cost: number;
  bonus: number;
  streak: { current: number; longest: number; run_started_on: string | null; alive: boolean };
};

export type Plan = {
  key: string;
  name: string;
  kind: "one_time" | "recurring";
  credits: number;
  period_days: number;
  price_paise: number;
  max_quantity: number;
};

export type PlanPeriod = {
  plan: string;
  plan_name: string;
  status: "active" | "queued";
  starts_at: string;
  ends_at: string;
  credits: number;
};

export type OneTimeRules = { min_credits: number; max_credits: number; price_paise_per_credit: number; valid_days: number };

export type Plans = {
  plans: Plan[];
  one_time: OneTimeRules | null;
  periods: PlanPeriod[];
  queue: { open: number; limit: number };
};
