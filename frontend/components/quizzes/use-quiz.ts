"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { quizzesApi } from "@/lib/quizzes-api";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import type { NodeStatus, QuizDetail, RunEvent } from "@/lib/types";

const POLL_MS = 4000;

/**
 * Loads a quick quiz and keeps it current: follows the run that is making or retaking it, refetches when a run segment
 * ends, and polls slowly as a safety net while it is working. `nodeStatus` says which steps have run, for the progress
 * screen.
 */
export function useQuiz(id: string) {
  const [quiz, setQuiz] = useState<QuizDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Which steps have run, for the run they belong to (a new run starts from nothing, without a reset in an effect).
  const [steps, setSteps] = useState<{ runId: string; status: Record<string, NodeStatus> } | null>(null);

  const refresh = useCallback(async () => {
    try {
      setQuiz(await quizzesApi.get(id));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? "not_found" : "We couldn't load this quiz.");
    }
  }, [id]);

  useEffect(() => {
    let active = true;
    quizzesApi
      .get(id)
      .then((data) => active && setQuiz(data))
      .catch((err) => active && setError(err instanceof ApiError && err.status === 404 ? "not_found" : "We couldn't load this quiz."));
    return () => {
      active = false;
    };
  }, [id]);

  const runId = quiz?.run_id ?? null;
  useEffect(() => {
    if (!runId) return;
    const stream = new RunEventStream(runId, (event: RunEvent) => {
      if (event.name === "snapshot") setSteps({ runId, status: event.data.node_status });
      if (event.name === "node") {
        setSteps((current) => ({ runId, status: { ...(current?.runId === runId ? current.status : {}), [event.data.node]: event.data.status } }));
      }
      if (TERMINAL_EVENTS.has(event.name)) void refresh();
    });
    return () => stream.close();
  }, [runId, refresh]);

  const working = quiz ? quiz.stage === "preparing" || quiz.run_id !== null : false;
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [working, refresh]);

  return { quiz, error, refresh, nodeStatus: steps && steps.runId === runId ? steps.status : {} };
}
