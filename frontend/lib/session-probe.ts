type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/**
 * Whether anyone is signed in, learned without a request that fails. The session marker is httpOnly, so the page cannot
 * read it, and `/auth/me` for a signed-out visitor is a 401 the browser prints in red (and a failed `/auth/refresh`
 * behind it) on every public page. The server can read the marker: `GET /api/session` says what it finds. It is a hint
 * only; the API still authorises every request.
 */
export class SessionProbe {
  static readonly COOKIE = "lc_session";
  static readonly PATH = "/api/session";

  /** Server side: the request carries the marker. */
  static signedIn(cookies: { has(name: string): boolean }): boolean {
    return cookies.has(SessionProbe.COOKIE);
  }

  /** Page side. Anything but a clear "no" counts as "yes", so a hiccup never hides a signed-in learner. */
  static async ask(fetcher: Fetch = (input, init) => fetch(input, init)): Promise<boolean> {
    try {
      const response = await fetcher(SessionProbe.PATH, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) return true;
      const body: unknown = await response.json();
      return !(body && typeof body === "object" && (body as { signedIn?: unknown }).signedIn === false);
    } catch {
      return true;
    }
  }
}
