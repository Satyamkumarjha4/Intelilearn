"use client";

import { Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AttemptRunner } from "@/components/lessons/attempt-runner";
import { QuizResult } from "@/components/quizzes/quiz-result";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { AttemptPreparation } from "@/lib/attempt-flow";
import { QuizMessages } from "@/lib/quiz-messages";
import { QuizStageView } from "@/lib/quiz-stage-view";
import { quizzesApi } from "@/lib/quizzes-api";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import type { LearnerTest, QuizAttempt, QuizDetail } from "@/lib/types";

type Props = { quiz: QuizDetail; onChanged: () => void };

type View =
  | { kind: "loading" }
  | { kind: "taking"; test: LearnerTest }
  | { kind: "preparing" }
  | { kind: "results"; attempt: QuizAttempt };

/**
 * The part of the quiz page that is the quiz itself: an attempt to take (resumed after a refresh, with the answers
 * already locked), the questions of a new try being written, or the result of the latest try with the history and a
 * button to try again. What it shows is decided by what the server says the quiz is (`QuizStageView`).
 */
export function QuizTaker({ quiz, onChanged }: Props) {
  const router = useRouter();
  const [view, setView] = useState<View>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [trying, setTrying] = useState(false);
  const [cancellable, setCancellable] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const preparing = useRef<AttemptPreparation | null>(null);
  useEffect(() => () => preparing.current?.dispose(), []);

  const showLatest = async () => {
    const detail = await quizzesApi.get(quiz.id);
    const target = QuizStageView.of(detail);
    if (target.kind === "results") setView({ kind: "results", attempt: await quizzesApi.attempt(quiz.id, target.attemptId) });
    else if (target.kind === "taking") setView({ kind: "taking", test: await quizzesApi.test(quiz.id) });
  };

  const begin = async () => {
    setTrying(true);
    const run = new AttemptPreparation(quizzesApi, (runId, onEnd) => {
      const events = new RunEventStream(runId, (event) => TERMINAL_EVENTS.has(event.name) && onEnd());
      return () => events.close();
    });
    preparing.current = run;
    try {
      const outcome = await run.run(quiz.id, () => {
        setCancellable(run.cancellable);
        setView({ kind: "preparing" });
      });
      onChanged();
      if (outcome.kind === "ready") {
        setView({ kind: "taking", test: outcome.test });
      } else {
        if (outcome.kind === "failed") toast.error("We couldn't get your questions ready. Nothing was lost: try again.");
        else toast.message("Stopped. Nothing was used: you can try again whenever you like.");
        await showLatest();
      }
    } catch (err) {
      toast.error(QuizMessages.retake(err));
      await showLatest().catch(() => undefined);
    } finally {
      setTrying(false);
      setCancellable(false);
      setCancelling(false);
    }
  };

  const target = QuizStageView.of(quiz);
  const targetKind = target.kind;
  const attemptId = target.kind === "taking" || target.kind === "results" ? target.attemptId : null;
  useEffect(() => {
    let active = true;
    const load = async () => {
      if (targetKind === "taking") setView({ kind: "taking", test: await quizzesApi.test(quiz.id) });
      else if (targetKind === "preparing") void begin(); // a refresh while the questions were being written
      else if (targetKind === "results" && attemptId) setView({ kind: "results", attempt: await quizzesApi.attempt(quiz.id, attemptId) });
    };
    load().catch((err) => active && setError(err instanceof ApiError ? err.message : "We couldn't load your quiz."));
    return () => {
      active = false;
    };
    // The panel follows the quiz's own screen: it loads again when the attempt on show changes, not on every refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quiz.id, targetKind, attemptId]);

  const cancel = async () => {
    setCancelling(true);
    try {
      await preparing.current?.cancel();
    } catch (err) {
      toast.error(QuizMessages.retake(err));
      setCancelling(false);
    }
  };

  const select = async (id: string) => {
    try {
      setView({ kind: "results", attempt: await quizzesApi.attempt(quiz.id, id) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "We couldn't load that try.");
    }
  };

  const createLesson = async (id: string) => {
    const { lesson_id } = await quizzesApi.createLesson(quiz.id, id);
    router.push(`/lessons/${lesson_id}`);
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
    case "preparing":
      return (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
            <Loader2Icon className="size-10 text-primary motion-safe:animate-spin" aria-hidden="true" />
            <h2 className="font-heading text-2xl font-semibold">Getting your questions ready</h2>
            <p className="max-w-prose text-muted-foreground" aria-live="polite">
              Fresh questions are being written for you. This takes a moment, and you can leave this page: they&apos;ll be here when you come back.
            </p>
            {cancellable && (
              <Button variant="outline" onClick={() => void cancel()} disabled={cancelling}>
                {cancelling ? "Stopping…" : "Cancel"}
              </Button>
            )}
          </CardContent>
        </Card>
      );
    case "taking":
      return (
        <AttemptRunner<QuizAttempt>
          key={view.test.attempt!.id}
          lessonId={quiz.id}
          test={view.test}
          api={quizzesApi}
          kind="quiz"
          onChanged={onChanged}
          onSubmitted={(attempt) => {
            setView({ kind: "results", attempt });
            onChanged();
          }}
        />
      );
    case "results":
      return (
        <QuizResult
          key={view.attempt.id}
          quiz={quiz}
          attempt={view.attempt}
          trying={trying}
          onTryAgain={() => void begin()}
          onSelect={(id) => void select(id)}
          onCreateLesson={createLesson}
        />
      );
  }
}
