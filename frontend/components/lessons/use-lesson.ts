"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { PipelineModel } from "@/lib/pipeline";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import { StageView } from "@/lib/stage-view";
import type { LessonDetail, RunEvent } from "@/lib/types";

const POLL_MS = 4000;

function describe(err: unknown): string {
  return err instanceof ApiError && err.status === 404 ? "not_found" : "Could not load this lesson.";
}

/**
 * Loads a lesson and keeps it current: follows the active run's events, refetches when a run segment ends
 * (the lesson has moved to its next stage), and polls slowly as a safety net while it is working.
 */
export function useLesson(id: string) {
  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<{ runId: string; model: PipelineModel } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await lessonsApi.get(id);
      setLesson(data);
      // A retry starts while the lesson still reads "failed"; the stage that follows tells the model which steps to show.
      setLive((current) => {
        if (!current) return current;
        current.model.setStage(data.stage);
        return { ...current };
      });
      setError(null);
    } catch (err) {
      setError(describe(err));
    }
  }, [id]);

  useEffect(() => {
    let active = true;
    lessonsApi
      .get(id)
      .then((data) => active && setLesson(data))
      .catch((err) => active && setError(describe(err)));
    return () => {
      active = false;
    };
  }, [id]);

  const runId = lesson?.active_run_id ?? null;
  const stage = lesson?.stage;
  const route = lesson?.route ?? "";
  useEffect(() => {
    if (!runId || !stage) return;
    const model = new PipelineModel(stage, Date.now, route);
    const stream = new RunEventStream(runId, (event: RunEvent) => {
      model.apply(event);
      setLive({ runId, model });
      if (TERMINAL_EVENTS.has(event.name)) void refresh();
    });
    return () => stream.close();
    // `stage` and `route` are read once per run: a stage change within a run must not restart the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, refresh]);

  const idle = useMemo(() => new PipelineModel(stage ?? "preparing_diagnostic", Date.now, route), [stage, route]);

  const working = lesson ? StageView.of(lesson) === "progress" || lesson.active_run_id !== null : false;
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [working, refresh]);

  return { lesson, error, refresh, pipeline: live && live.runId === runId ? live.model : idle };
}
