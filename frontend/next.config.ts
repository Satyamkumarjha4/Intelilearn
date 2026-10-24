import path from "node:path";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// One .env for the whole project lives at the repo root. On the host this loads it; inside docker it
// isn't mounted and compose provides the variables instead. Already-set variables are never overridden.
loadEnvConfig(path.resolve(process.cwd(), ".."));

// Browser-facing Django URL (Swagger/admin links); inlined into the client bundle at build time.
process.env.NEXT_PUBLIC_BACKEND_URL ??= `http://localhost:${process.env.BACKEND_PORT ?? "8000"}`;

// The browser only ever talks to this origin: /api/* is proxied to Django by app/api/[...path]/route.ts,
// so auth cookies and EventSource work without CORS. Django API routes have no trailing slash.
const nextConfig: NextConfig = {};

export default nextConfig;
