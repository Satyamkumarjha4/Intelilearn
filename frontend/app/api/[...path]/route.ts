import type { NextRequest } from "next/server";

// Same-origin proxy from the browser to Django: /api/* → ${DJANGO_API_ORIGIN}/api/*.
// A route handler (not a next.config rewrite) so we control the forwarded headers: rewrites drop the
// X-Forwarded-For that Next computes from the socket, which made Django see one address (this container)
// for every visitor and put everyone in one auth rate-limit bucket.
//
// Request bodies are buffered rather than streamed: forwarding the incoming ReadableStream directly makes
// undici send it chunked with no Content-Length, and uvicorn/Django then reads an empty body (confirmed
// against this backend). Buffering is fine for JSON API calls; it would need revisiting for large uploads.
// Response bodies ARE streamed through as-is, so Server-Sent Events (the run-progress endpoint) work.
//
// In production, a reverse proxy in front of Next must overwrite X-Forwarded-For with the real client
// address, otherwise a client can pick its own value.

export const dynamic = "force-dynamic";

const DJANGO = process.env.DJANGO_API_ORIGIN ?? `http://localhost:${process.env.BACKEND_PORT ?? "8000"}`;

// Connection-level headers that must not be forwarded, plus ones fetch recomputes.
const REQUEST_SKIP = ["connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade", "te", "trailer",
  "host", "content-length", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"]; // prettier-ignore
const RESPONSE_SKIP = ["connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"];

async function forward(request: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, DJANGO);

  const headers = new Headers(request.headers);
  REQUEST_SKIP.forEach((name) => headers.delete(name));
  // Next fills x-forwarded-for from the socket when the client didn't send one; keep only the first entry.
  const client = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  if (client) headers.set("x-forwarded-for", client);
  headers.set("x-forwarded-host", request.headers.get("host") ?? "");
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: request.signal,
    });
  } catch {
    return Response.json({ detail: "The API is unreachable.", code: "bad_gateway" }, { status: 502 });
  }

  const responseHeaders = new Headers(upstream.headers); // keeps multiple Set-Cookie headers intact
  RESPONSE_SKIP.forEach((name) => responseHeaders.delete(name));
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders });
}

export { forward as DELETE, forward as GET, forward as HEAD, forward as OPTIONS, forward as PATCH, forward as POST, forward as PUT };
