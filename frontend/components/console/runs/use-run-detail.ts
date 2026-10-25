"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { consoleApi } from "@/lib/console-api";
import { RunEventStream } from "@/lib/run-events";
import { RunFollower } from "@/lib/run-follower";
import { RunText } from "@/lib/run-text";
import type { RunDetail } from "@/lib/types";

/**
 * One run's detail, kept current while the run is moving (events when the stream is open to us, polling when it is
 * not: see `RunFollower`). `onEnded` is called once when a run that was moving is seen to be over, so the list can
 * refresh its row.
 */
export function useRunDetail(id: string | null, onEnded: () => void) {
  const [state, setState] = useState<{ id: string; detail: RunDetail } | null>(null);
  const [error, setError] = useState<{ id: string; message: string } | null>(null);
  const ended = useRef(onEnded);
  useEffect(() => {
    ended.current = onEnded;
  });

  useEffect(() => {
    if (!id) return;
    let wasActive = false;
    const follower = new RunFollower({
      load: () => consoleApi.run(id),
      onDetail: (detail) => {
        setState({ id, detail });
        setError(null);
        const active = RunText.isActive(detail.status);
        if (wasActive && !active) ended.current();
        wasActive = active;
      },
      onError: (err) => setError({ id, message: err instanceof ApiError && err.status === 404 ? "not_found" : "We couldn't load this run." }),
      open: (onEvent) => new RunEventStream(id, onEvent),
    });
    follower.start();
    return () => follower.stop();
  }, [id]);

  /** Loads the run once more, for after an action. */
  const reload = useCallback(async () => {
    if (!id) return;
    try {
      setState({ id, detail: await consoleApi.run(id) });
    } catch {
      // the follower reports it
    }
  }, [id]);

  return {
    detail: state && state.id === id ? state.detail : null,
    error: error && error.id === id ? error.message : null,
    reload,
  };
}
