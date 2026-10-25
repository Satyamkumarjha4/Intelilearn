import type { NextRequest } from "next/server";

import { SessionProbe } from "@/lib/session-probe";

// Whether the request carries the session marker, so a signed-out page does not ask `/auth/me` and print a 401 (see
// `SessionProbe`). More specific than the catch-all proxy next to it, so it never reaches Django. Always 200.
export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  return Response.json({ signedIn: SessionProbe.signedIn(request.cookies) }, { headers: { "Cache-Control": "no-store" } });
}
