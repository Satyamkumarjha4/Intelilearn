"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AttemptRunner } from "@/components/lessons/attempt-runner";
import { TestResults } from "@/components/lessons/test-results";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AttemptErrors, AttemptPreparation } from "@/lib/attempt-flow";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import type { AttemptHistory, LearnerTest, TestSubmission } from "@/lib/types";

type Props = { lessonId: string; lessonTitle: string; onChanged: () => void; onOpenLesson: () => void };

type View =
  | { kind: "loading" }
  | { kind: "intro" }
  | { kind: "preparing" }
  | { kind: "taking"; test: LearnerTest }
  | { kind: "results"; attempt: TestSubmission };

/**
 * The Test tab. It shows whatever the server says the test is: an attempt to take (resumed after a refresh, with the
 * answers already locked), questions being written for a retake, the result of an attempt with the history of every
 * try and a Try again button, or the first attempt waiting to be started.
 */
export function TestTabPanel({ lessonId, lessonTitle, onChanged, onOpenLesson }: Props) {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [history, setHistory] = useState<AttemptHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [trying, setTrying] = useState(false);
  const preparing = useRef<AttemptPreparation | null>(null);
  useEffect(() => () => preparing.current?.dispose(), []);

  const latestSealed = (data: AttemptHistory) => [...data.attempts].reverse().find((a) => a.status !== "generating" && a.status !== "in_progress");

  const showLatest = async (data: AttemptHistory): Promise<void> => {
    const latest = latestSealed(data);
    setView(latest ? { kind: "results", attempt: await lessonsApi.attempt(lessonId, latest.id) } : { kind: "intro" });
  };

  const begin = async () => {
    setTrying(true);
    const run = new AttemptPreparation(lessonsApi, (runId, onEnd) => {
      const events = new RunEventStream(runId, (event) => TERMINAL_EVENTS.has(event.name) && onEnd());
      return () => events.close();
    });
    preparing.current = run;
    try {
      const outcome = await run.run(lessonId, () => setView({ kind: "preparing" }));
      onChanged();
      if (outcome.kind === "ready") {
        setView({ kind: "taking", test: outcome.test });
      } else {
        toast.error("We couldn't get your questions ready. Nothing was lost: try again.");
        const data = await lessonsApi.attempts(lessonId);
        setHistory(data);
        await showLatest(data);
      }
    } catch (err) {
      toast.error(AttemptErrors.message(err, "We couldn't start your test."));
      if (history) await showLatest(history);
      else setView({ kind: "intro" });
    } finally {
      setTrying(false);
    }
  };

  useEffect(() => {
    let active = true;
    const load = async () => {
      const [test, data] = await Promise.all([lessonsApi.test(lessonId), lessonsApi.attempts(lessonId)]);
      if (!active) return;
      setHistory(data);
      if (test.attempt?.status === "in_progress") setView({ kind: "taking", test });
      else if (test.attempt?.status === "generating") void begin(); // a refresh while the questions were being written
      else await showLatest(data);
    };
    load().catch((err) => active && setError(err instanceof ApiError ? err.message : "Could not load your test."));
    return () => {
      active = false;
    };
    // The panel loads once for the lesson; begin and showLatest only read this lesson's id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonId]);

  const handedIn = async (attempt: TestSubmission) => {
    setView({ kind: "results", attempt });
    setHistory(await lessonsApi.attempts(lessonId));
    onChanged();
  };

  const select = async (attemptId: string) => {
    try {
      setView({ kind: "results", attempt: await lessonsApi.attempt(lessonId, attemptId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not load that attempt.");
    }
  };

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  switch (view.kind) {
    case "loading":
      return <Skeleton className="h-72 rounded-[22px]" />;
    case "intro":
      return <TestIntro starting={trying} onStart={() => void begin()} />;
    case "preparing":
      return <PreparingQuestions />;
    case "taking":
      return <AttemptRunner key={view.test.attempt!.id} lessonId={lessonId} test={view.test} onChanged={onChanged} onSubmitted={(attempt) => void handedIn(attempt)} />;
    case "results":
      return (
        <TestResults
          key={view.attempt.id}
          lessonId={lessonId}
          lessonTitle={lessonTitle}
          attempt={view.attempt}
          history={history}
          trying={trying}
          onTryAgain={() => void begin()}
          onSelect={(id) => void select(id)}
          onOpenLesson={onOpenLesson}
        />
      );
  }
}

function TestIntro({ starting, onStart }: { starting: boolean; onStart: () => void }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
        <h2 className="font-heading text-2xl font-semibold">Ready for the test?</h2>
        <p className="max-w-prose text-muted-foreground">
          You&apos;ll answer one question at a time, and once you move on you can&apos;t go back. You&apos;ll see your score straight away, and you can try again whenever you like with new questions.
        </p>
        <Button variant="marigold" onClick={onStart} disabled={starting}>
          {starting ? "Starting…" : "Start the test"}
        </Button>
      </CardContent>
    </Card>
  );
}

function PreparingQuestions() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
        <Loader2Icon className="size-10 text-primary motion-safe:animate-spin" aria-hidden="true" />
        <h2 className="font-heading text-2xl font-semibold">Getting your questions ready</h2>
        <p className="max-w-prose text-muted-foreground" aria-live="polite">
          Fresh questions are being written for you. This takes a moment, and you can leave this page: they&apos;ll be here when you come back.
        </p>
      </CardContent>
    </Card>
  );
}
