import type { NextRequest } from "next/server";

import { ClientAddress } from "@/lib/client-address";

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
// In production, a reverse proxy in front of Next must overwrite X-Forwarded-For with the real client address, or append
// it to what the client sent (set EDGE_PROXY_HOPS to how many such proxies there are, default 1: the last entry counts).
// With no proxy in front, a client that sends a single X-Forwarded-For chooses its own address: nothing in the app can
// tell it from the real one, so the address limits are only as good as the edge (docs/reference/api.md).

export const dynamic = "force-dynamic";

const DJANGO = process.env.DJANGO_API_ORIGIN ?? `http://localhost:${process.env.BACKEND_PORT ?? "8000"}`;
const HOPS = ClientAddress.hops(process.env.EDGE_PROXY_HOPS);

// Connection-level headers that must not be forwarded, plus ones fetch recomputes.
const REQUEST_SKIP = ["connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade", "te", "trailer",
  "host", "content-length", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"]; // prettier-ignore
const RESPONSE_SKIP = ["connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"];

async function forward(request: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, DJANGO);

  const headers = new Headers(request.headers);
  REQUEST_SKIP.forEach((name) => headers.delete(name));
  // Next fills x-forwarded-for from the socket only when the client sent none, and an edge proxy appends to what the client
  // sent. So the first entry is the client's own claim; the one that counts is what a proxy of ours added (`ClientAddress`).
  const client = ClientAddress.of(request.headers.get("x-forwarded-for"), HOPS);
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
