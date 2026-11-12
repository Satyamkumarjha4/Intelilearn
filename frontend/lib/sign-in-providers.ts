import { apiClient, type ApiClient } from "@/lib/api";

export type SignInProvider = { key: string; label: string };

/**
 * Which "Continue with ..." buttons to draw, and where they go. The list comes from `GET /api/auth/providers`, which names only
 * the providers that are on, so a screen never shows a button that cannot work. When the call fails the answer is "none": the
 * email form is always there, and a missing button is better than a broken one.
 */
export class SignInProviders {
  static readonly PATH = "/auth/providers";

  constructor(private readonly client: ApiClient = apiClient) {}

  /** The providers that are on, or none when the list cannot be read. */
  async load(): Promise<SignInProvider[]> {
    try {
      const { providers } = await this.client.request<{ providers: SignInProvider[] }>(SignInProviders.PATH);
      return SignInProviders.clean(providers);
    } catch {
      return [];
    }
  }

  /** Only entries that have a key and a label are kept, so a malformed answer draws nothing. */
  static clean(value: unknown): SignInProvider[] {
    if (!Array.isArray(value)) return [];
    return value.filter(
      (item): item is SignInProvider => typeof item?.key === "string" && /^[a-z][a-z0-9_-]*$/.test(item.key) && typeof item?.label === "string" && item.label !== "",
    );
  }

  /** The address that starts signing in with a provider. It is a whole-page navigation (the provider's page is another site). */
  static startHref(provider: SignInProvider, next: string, defaultNext = "/lessons"): string {
    const query = next && next !== defaultNext ? `?next=${encodeURIComponent(next)}` : "";
    return `/api/auth/oauth/${provider.key}/start${query}`;
  }

  /** The words on the button. */
  static buttonLabel(provider: SignInProvider): string {
    return `Continue with ${provider.label}`;
  }
}
