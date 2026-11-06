"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";

/** Loads one thing when the page opens: the data, the error in words, and a way to load it again. */
export function useLoaded<T>(load: () => Promise<T>, failure: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let active = true;
    load()
      .then((value) => {
        if (!active) return;
        setData(value);
        setError(null);
      })
      .catch((err) => active && setError(err instanceof ApiError ? err.message : failure));
    return () => {
      active = false;
    };
    // `load` and `failure` are written inline by the page; `round` says when to load again
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [round]);

  const reload = useCallback(() => setRound((n) => n + 1), []);
  return { data, error, reload };
}
