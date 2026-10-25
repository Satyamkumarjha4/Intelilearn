// Browser-side API client. Every call goes to same-origin /api/*, which app/api/[...path]/route.ts proxies to
// Django. Auth lives in httpOnly cookies set by the API, so there are no tokens to handle here — only:
//   - the CSRF header on unsafe methods (Django checks it for cookie-authenticated requests)
//   - one silent POST /api/auth/refresh + retry when a request comes back 401

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields: FieldErrors = {},
    /** Whatever else the error body carried (for example `submission_id` on `already_submitted`). */
    readonly extra: Record<string, unknown> = {},
    /** Seconds the server asks the client to wait (the `Retry-After` header of a 429), when it said. */
    readonly retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type RequestOptions = { method?: string; body?: unknown };

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// Auth endpoints never trigger the refresh-and-retry (it would loop or hide a real 401).
const NO_REFRESH_PATHS = new Set(["/auth/login", "/auth/register", "/auth/refresh", "/auth/logout", "/auth/csrf"]);

function documentCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

export class ApiClient {
  private refreshing: Promise<boolean> | null = null;

  // Collaborators are injected so tests can drive the client without a browser or a server.
  constructor(
    private readonly fetcher: Fetch = (input, init) => fetch(input, init),
    private readonly readCookie: (name: string) => string | null = documentCookie,
  ) {}

  async request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
    const method = (options.method ?? "GET").toUpperCase();

    const send = async () => {
      const headers: Record<string, string> = { Accept: "application/json" };
      if (options.body !== undefined) headers["Content-Type"] = "application/json";
      if (UNSAFE_METHODS.has(method)) headers["X-CSRFToken"] = await this.csrfToken();
      return this.fetcher(`/api${path}`, {
        method,
        headers,
        credentials: "same-origin",
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    };

    let response = await send();
    if (response.status === 401 && !NO_REFRESH_PATHS.has(path) && (await this.refreshSession())) {
      response = await send();
    }
    if (!response.ok) throw await this.toApiError(response);
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  /** Renew the access cookie. Concurrent 401s share one refresh request. */
  refreshSession(): Promise<boolean> {
    this.refreshing ??= (async () => {
      try {
        const response = await this.fetcher("/api/auth/refresh", {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": await this.csrfToken() },
        });
        return response.ok;
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }

  private async csrfToken(): Promise<string> {
    let token = this.readCookie("csrftoken");
    if (!token) {
      await this.fetcher("/api/auth/csrf", { credentials: "same-origin" });
      token = this.readCookie("csrftoken");
    }
    return token ?? "";
  }

  private static retryAfterOf(response: Response): number | null {
    const seconds = Number(response.headers?.get("Retry-After"));
    return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null;
  }

  private async toApiError(response: Response): Promise<ApiError> {
    const body = await response.json().catch(() => null);
    const { detail, code, fields, ...extra } = body && typeof body === "object" ? body : ({} as Record<string, unknown>);
    return new ApiError(
      response.status,
      code ?? "error",
      detail ?? `Request failed (${response.status})`,
      fields ?? {},
      extra,
      ApiClient.retryAfterOf(response),
    );
  }
}

/** The client components use; one instance so concurrent 401s share a single refresh. */
export const apiClient = new ApiClient();
