"use client";

import { useCallback, useEffect, useState } from "react";

type Component = { ok: boolean; latency_ms: number; detail: string };
type Health = { status: "ok" | "degraded"; database: Component; redis: Component; celery: Component };

const LABELS: Record<keyof Omit<Health, "status">, string> = {
  database: "Database (Supabase)",
  redis: "Redis",
  celery: "Celery worker",
};

type Result = { health: Health | null; error: string | null };

async function fetchHealth(): Promise<Result> {
  try {
    // Same-origin call, proxied to Django by the rewrite in next.config.ts.
    // The API answers 503 with the same body when a component is down.
    const response = await fetch("/api/health", { cache: "no-store" });
    return { health: (await response.json()) as Health, error: null };
  } catch {
    return { health: null, error: "Could not reach the API through /api. Is the backend container running?" };
  }
}

export function SystemStatus() {
  const [{ health, error }, setResult] = useState<Result>({ health: null, error: null });
  const [loading, setLoading] = useState(true);

  const apply = useCallback((result: Result) => {
    setResult(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    let active = true;
    fetchHealth().then((result) => active && apply(result));
    return () => {
      active = false;
    };
  }, [apply]);

  const recheck = () => {
    setLoading(true);
    fetchHealth().then(apply);
  };

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-zinc-200 p-6 dark:border-zinc-800">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">System status</h2>
        <button
          onClick={recheck}
          disabled={loading}
          className="rounded-md border border-zinc-300 px-3 py-1 text-sm disabled:opacity-50 dark:border-zinc-700"
        >
          {loading ? "Checking…" : "Recheck"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {health && (
        <ul className="flex flex-col gap-2 text-sm">
          {(Object.keys(LABELS) as (keyof typeof LABELS)[]).map((key) => (
            <li key={key} className="flex items-start justify-between gap-4">
              <span className="flex items-center gap-2">
                <span className={`size-2 rounded-full ${health[key].ok ? "bg-green-500" : "bg-red-500"}`} />
                {LABELS[key]}
              </span>
              <span className="truncate text-right text-zinc-500">
                {health[key].detail} · {health[key].latency_ms} ms
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
