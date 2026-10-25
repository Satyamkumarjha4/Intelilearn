import { NextResponse, type NextRequest } from "next/server";

import { RouteGuard } from "@/lib/route-guard";
import { SetupMarker } from "@/lib/setup-marker";

// Route guard (Next 16 `proxy`, formerly middleware). It only reads the marker cookies the API sets
// (see backend/accounts/cookies.py) to pick the right page; the API still authorises every request.
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const target = RouteGuard.redirectFor(pathname, search, {
    signedIn: request.cookies.has("lc_session"),
    onboarded: request.cookies.has("lc_onboarded"),
    settingUp: request.cookies.has(SetupMarker.COOKIE),
  });
  return target ? NextResponse.redirect(new URL(target, request.url)) : NextResponse.next();
}

export const config = {
  matcher: ["/", "/auth", "/onboarding", "/profile/:path*", "/lessons/:path*", "/console/:path*"],
};
