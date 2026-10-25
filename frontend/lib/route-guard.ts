import { RedirectPolicy } from "@/lib/safe-redirect";

/** `settingUp`: in the last step of the setup, whose profile is saved already (see `SetupMarker`). */
export type Visitor = { signedIn: boolean; onboarded: boolean; settingUp?: boolean };

const PROTECTED = ["/onboarding", "/profile", "/lessons"];

/**
 * Where a visitor may be, from the marker cookies the API sets (backend/accounts/cookies.py). `proxy.ts` asks it and
 * redirects; the API still authorises every request. "/" is the landing page for signed-out visitors only.
 */
export class RouteGuard {
  /** The path to redirect to, or `null` to let the request through. */
  static redirectFor(pathname: string, search: string, visitor: Visitor): string | null {
    const next = RedirectPolicy.safeNext(new URLSearchParams(search).get("next"), "");
    if (pathname === "/" || pathname === "/auth") return visitor.signedIn ? RouteGuard.arrival(visitor, pathname === "/auth" ? next : "") : null;
    // Nothing left to set up, unless this is a refresh on the last step: the profile saves at step 4, which is "onboarded".
    if (pathname === "/onboarding" && visitor.signedIn && visitor.onboarded && !visitor.settingUp) return next || "/lessons";
    if (RouteGuard.isConsole(pathname)) return visitor.signedIn ? null : `/auth?next=${encodeURIComponent(pathname + search)}`;
    if (!PROTECTED.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) return null;

    if (!visitor.signedIn) return `/auth?next=${encodeURIComponent(pathname + search)}`;
    if (!visitor.onboarded && pathname !== "/onboarding") return RouteGuard.setup(pathname + search);
    return null;
  }

  /** The staff console needs a session but not onboarding; the API (and the console layout) decide who is staff. */
  private static isConsole(pathname: string): boolean {
    return pathname === "/console" || pathname.startsWith("/console/");
  }

  /** Where a signed-in visitor starts: where they were headed (a safe path), else their lessons; through the setup first. */
  private static arrival(visitor: Visitor, next: string): string {
    return visitor.onboarded ? next || "/lessons" : RouteGuard.setup(next);
  }

  /** The setup, which carries on to `target` when it is done. */
  private static setup(target: string): string {
    return !target || target === "/lessons" ? "/onboarding" : `/onboarding?next=${encodeURIComponent(target)}`;
  }
}
