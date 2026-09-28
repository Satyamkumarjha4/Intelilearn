import { NextResponse, type NextRequest } from "next/server";

// Route guard (Next 16 `proxy`, formerly middleware). It only reads the marker cookies the API sets
// (see backend/accounts/cookies.py) to pick the right page; the API still authorises every request.
const SIGNED_IN = "lc_session";
const ONBOARDED = "lc_onboarded";

const PROTECTED = ["/onboarding", "/profile", "/lessons"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = request.cookies.has(SIGNED_IN);
  const onboarded = request.cookies.has(ONBOARDED);
  const redirect = (path: string) => NextResponse.redirect(new URL(path, request.url));

  if (pathname === "/auth") {
    return signedIn ? redirect(onboarded ? "/" : "/onboarding") : NextResponse.next();
  }

  const isProtected = PROTECTED.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  if (!isProtected) return NextResponse.next();

  if (!signedIn) {
    return redirect(`/auth?next=${encodeURIComponent(pathname + search)}`);
  }
  if (!onboarded && pathname !== "/onboarding") {
    return redirect("/onboarding");
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/auth", "/onboarding", "/profile/:path*", "/lessons/:path*"],
};
