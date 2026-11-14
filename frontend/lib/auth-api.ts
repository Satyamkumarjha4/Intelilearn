import { apiClient, type ApiClient } from "@/lib/api";
import { type CaptchaConfig, CaptchaRules } from "@/lib/captcha";
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

  /** Ask for a code to choose a new password. Always accepted, whether or not the address has an account; a refusal is a 429. */
  async forgot(email: string): Promise<void> {
    await this.client.request("/auth/password/forgot", { method: "POST", body: { email } });
  }

  /** Choose a new password with the emailed code: the person is signed in and every older session ends. A weak password is a
   *  400 with `fields.new_password`; a wrong code is the usual `invalid_code`. */
  async reset(email: string, code: string, newPassword: string): Promise<User> {
    return (await this.client.request<{ user: User }>("/auth/password/reset", { method: "POST", body: { email, code, new_password: newPassword } })).user;
  }

  /** Who is waiting at the last step of a first sign-in with a provider: the address the provider gave, and its name for them. */
  async finishInfo(): Promise<{ email: string; name: string }> {
    return this.client.request<{ email: string; name: string }>("/auth/oauth/finish");
  }

  /** Take the last step: the name and the terms (and the browser's time zone). The account is made now and the person is signed in. */
  async finish(name: string, acceptTerms: boolean, timezone: string | null): Promise<User> {
    const body = { name, accept_terms: acceptTerms, ...(timezone ? { timezone } : {}) };
    return (await this.client.request<{ user: User }>("/auth/oauth/finish", { method: "POST", body })).user;
  }

  /** Ask for a new code. Always accepted; a refusal is a 429 with `Retry-After`, or a 400 `captcha_failed` when the
   *  sign-up check is on and `captchaToken` is missing or did not pass. */
  async resend(email: string, purpose: CodePurpose, captchaToken: string | null = null): Promise<void> {
    await this.client.request("/auth/verify/resend", { method: "POST", body: CaptchaRules.withToken({ email, purpose }, captchaToken) });
  }

  /** Whether the sign-up check is on. A failed look is "off": the server is what insists on the check. */
  async captcha(): Promise<CaptchaConfig> {
    try {
      return CaptchaRules.parse(await this.client.request("/auth/captcha"));
    } catch {
      return CaptchaRules.OFF;
    }
  }
}
