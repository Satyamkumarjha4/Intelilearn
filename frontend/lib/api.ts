// Browser-side API client. Every call goes to same-origin /api/*, which next.config.ts proxies to Django.
// Auth lives in httpOnly cookies set by the API, so there are no tokens to handle here — only:
//   - the CSRF header on unsafe methods (Django checks it for cookie-authenticated requests)
//   - one silent POST /api/auth/refresh + retry when a request comes back 401

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields: FieldErrors = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// Auth endpoints never trigger the refresh-and-retry (it would loop or hide a real 401).
const NO_REFRESH_PATHS = new Set(["/auth/login", "/auth/register", "/auth/refresh", "/auth/logout", "/auth/csrf"]);

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function csrfToken(): Promise<string> {
  let token = readCookie("csrftoken");
  if (!token) {
    await fetch("/api/auth/csrf", { credentials: "same-origin" });
    token = readCookie("csrftoken");
  }
  return token ?? "";
}

let refreshing: Promise<boolean> | null = null;

/** Renew the access cookie. Concurrent 401s share one refresh request. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": await csrfToken() },
      });
      return response.ok;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null);
  return new ApiError(
    response.status,
    body?.code ?? "error",
    body?.detail ?? `Request failed (${response.status})`,
    body?.fields ?? {},
  );
}

export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method ?? "GET";

  const send = async () => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (UNSAFE_METHODS.has(method)) headers["X-CSRFToken"] = await csrfToken();
    return fetch(`/api${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  };

  let response = await send();
  if (response.status === 401 && !NO_REFRESH_PATHS.has(path) && (await refreshSession())) {
    response = await send();
  }
  if (!response.ok) throw await toApiError(response);
  return (response.status === 204 ? undefined : await response.json()) as T;
}
