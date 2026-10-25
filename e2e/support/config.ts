/** Where the stack is and who the staff user is (set by `make e2e`; the defaults match its defaults). */
export class E2E {
  static readonly STAFF_EMAIL = process.env.E2E_STAFF_EMAIL ?? "staff@example.com";
  static readonly STAFF_PASSWORD = process.env.E2E_STAFF_PASSWORD ?? "E2e-staff-pass-1";
  static readonly PASSWORD = "E2e-learner-pass-1";

  /** An address no other test (or earlier run) has used. */
  static email(label: string): string {
    return `${label}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  }
}
