/** The shapes of the console's sign-in endpoints (a learner's verification, the sign-ups waiting, the abuse board, the
 *  challenge switch). Nothing here ever holds a code, a hash or a key. */

export type VerificationSource = "code" | "google" | "microsoft" | "staff" | "operator" | "legacy" | "";
export type CodeState = "live" | "used" | "cancelled" | "dead" | "expired";

export type VerificationState = {
  verified: boolean;
  verified_at: string | null;
  source: VerificationSource;
  legacy: boolean;
  closed: boolean;
  erased: boolean;
  can_resend: boolean;
  can_mark_verified: boolean;
  can_unlock: boolean;
};
export type VerificationCodeRow = { purpose: string; created_at: string; expires_at: string; tries: number; max_tries: number; state: CodeState };
export type VerificationMailRow = { kind: string; status: string; error: string; created_at: string; sent_at: string | null };
export type VerificationPanel = {
  learner: { id: string; name: string; email: string };
  state: VerificationState;
  sign_in_methods: string[];
  identities: { provider: string; linked_at: string; last_sign_in_at: string | null; hosted_domain: string }[];
  codes: VerificationCodeRow[];
  mail: VerificationMailRow[];
  lock: { locked_until: string; strikes: number } | null;
  signup_record: { ip: string | null; email_domain: string; method: string; created_at: string } | null;
};

export type PendingSignupRow = {
  id: string;
  email: string;
  name: string;
  created_at: string;
  expires_at: string;
  code_tries: number | null;
  code_max_tries: number | null;
  code_expires_at: string | null;
  locked_until: string | null;
};
export type PendingSignupPage = { next: string | null; previous: string | null; results: PendingSignupRow[] };
export type SignupActionResult = { sent?: boolean; unlocked?: boolean; note: string };
export type SignupApproved = { learner_id: string; signs_in_with: "google_or_reset"; note: string };

export type AbuseDay = { day: string; accounts_made: number; codes_sent: number; failed_checks: number; disposable_refused: number; captcha_failed: number };
export type AbuseTop = { name: string; count: number };
export type ChallengeState = { captcha_enabled: boolean; configured: boolean; missing: string[]; provider: string };
export type AbuseReport = {
  days: AbuseDay[];
  top_addresses: AbuseTop[];
  top_domains: AbuseTop[];
  locked_emails: number;
  waiting_signups: number;
  challenge: ChallengeState;
};
