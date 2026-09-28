import path from "node:path";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// One .env for the whole project lives at the repo root. On the host this loads it; inside docker it
// isn't mounted and compose provides the variables instead. Already-set variables are never overridden.
loadEnvConfig(path.resolve(process.cwd(), ".."));

const backendPort = process.env.BACKEND_PORT ?? "8000";
// Server-side target of the /api proxy (http://backend:8000 inside docker compose).
const djangoOrigin = process.env.DJANGO_API_ORIGIN ?? `http://localhost:${backendPort}`;
// Browser-facing Django URL (Swagger/admin links); inlined into the client bundle at build time.
process.env.NEXT_PUBLIC_BACKEND_URL ??= `http://localhost:${backendPort}`;

const nextConfig: NextConfig = {
  // The browser only ever talks to this origin; /api/* is proxied to Django so
  // auth cookies and EventSource work without CORS. Django API routes have no trailing slash.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${djangoOrigin}/api/:path*` }];
  },
};

export default nextConfig;
