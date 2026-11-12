import { apiClient, type ApiClient } from "@/lib/api";
import type { User } from "@/lib/types";

export type CodePurpose = "signup" | "login";

/** The typed calls of the sign-in endpoints. Each is one request; what to do with the answer is the caller's. */
export class AuthApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  /** Start creating an account: a code is emailed and nothing exists yet, so there is no user to return. */
  async register(body: Record<string, unknown>): Promise<void> {
    await this.client.request("/auth/register", { method: "POST", body });
  }

  /** Sign in. Throws an `ApiError` with the code `verification_required` when the email was never proved (a code was sent). */
  async login(email: string, password: string): Promise<User> {
    return (await this.client.request<{ user: User }>("/auth/login", { method: "POST", body: { email, password } })).user;
  }

  /** Enter the emailed code: the account (made now, for a sign-up) with its session cookies. */
  async verify(email: string, code: string, purpose: CodePurpose): Promise<User> {
    return (await this.client.request<{ user: User }>("/auth/verify", { method: "POST", body: { email, code, purpose } })).user;
  }

  /** Ask for a new code. Always accepted; a refusal is a 429 with `Retry-After`. */
  async resend(email: string, purpose: CodePurpose): Promise<void> {
    await this.client.request("/auth/verify/resend", { method: "POST", body: { email, purpose } });
  }
}
