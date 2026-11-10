"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { CalibrationWalk, type WalkState } from "@/lib/calibration-walk";
import { quizzesApi } from "@/lib/quizzes-api";
import { cn } from "@/lib/utils";

const LETTERS = ["A", "B", "C", "D"];

type Props = { quizId: string; onFinished: () => void };

/**
 * The warm-up: five multiple-choice questions, one at a time, each answer final. The server picks every next question
 * (a little harder after a right answer, easier after a wrong one) and shows nothing about difficulty. After the last
 * one the quiz is written for the level the walk found, and `onFinished` lets the page follow that.
 */
export function CalibrationRunner({ quizId, onFinished }: Props) {
  const [state, setState] = useState<WalkState>({ kind: "loading" });
  const [pick, setPick] = useState<{ question: string; index: number } | null>(null);
  const walk = useRef<CalibrationWalk | null>(null);

  useEffect(() => {
    const one = new CalibrationWalk(quizzesApi, quizId, setState);
    walk.current = one;
    void one.start();
  }, [quizId]);

  useEffect(() => {
    if (state.kind === "done") onFinished();
  }, [state.kind, onFinished]);

  // The option picked belongs to the question it was picked on, so a new question starts with none.
  const picked = state.kind === "asking" && pick?.question === state.question.id ? pick.index : null;

  if (state.kind === "loading" || state.kind === "done") {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center" aria-live="polite">
          <Loader2Icon className="size-10 text-primary motion-safe:animate-spin" aria-hidden="true" />
          <h2 className="font-heading text-2xl font-semibold">{state.kind === "done" ? "Writing your quiz" : "Getting your warm-up"}</h2>
          {state.kind === "done" && <p className="text-muted-foreground">Your warm-up is done. We&apos;re writing questions at your level.</p>}
        </CardContent>
      </Card>
    );
  }
  if (state.kind === "error") {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
          <h2 className="font-heading text-2xl font-semibold">We couldn&apos;t get your next question</h2>
          <p className="text-muted-foreground">{state.message}</p>
          <Button variant="marigold" onClick={() => void walk.current?.start()}>
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const { step, total, question, saving } = state;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">Quick warm-up</p>
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-heading text-2xl font-semibold">
            Question {step} of {total}
          </h2>
          <span className="text-sm text-muted-foreground">Answers lock when you continue</span>
        </div>
        <Progress value={(step - 1) / total} label="How far through the warm-up" />
      </div>
      <Card>
        <CardContent className="flex flex-col gap-4">
          <Markdown className="font-heading text-lg leading-snug font-medium">{question.question}</Markdown>
          <div role="radiogroup" aria-label="Answers" className="flex flex-col gap-2">
            {question.options.map((option, index) => (
              <button
                key={index}
                type="button"
                role="radio"
                aria-checked={picked === index}
                disabled={saving}
                onClick={() => setPick({ question: question.id, index })}
                className={cn(
                  "flex items-center gap-3 rounded-xl border-2 px-3 py-2.5 text-left text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 hover:bg-muted",
                  picked === index ? "border-primary bg-primary-soft" : "border-border",
                )}
              >
                <span className={cn("grid size-6 shrink-0 place-items-center rounded-full font-mono text-xs font-bold", picked === index ? "bg-primary-action text-primary-foreground" : "bg-muted text-muted-foreground")}>
                  {LETTERS[index]}
                </span>
                {option}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button variant="ghost" disabled={saving} onClick={() => void walk.current?.answer(null)}>
              I don&apos;t know
            </Button>
            <Button variant="marigold" disabled={picked === null || saving} onClick={() => void walk.current?.answer(picked)}>
              {saving ? "Saving…" : step === total ? "Finish" : "Continue"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
