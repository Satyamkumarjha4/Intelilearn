"use client";

import { CheckIcon, LockIcon, MinusIcon, XIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { BandDots } from "@/components/lessons/band-dots";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { AnswersView } from "@/lib/answers-view";
import { DateText } from "@/lib/format";
import { lessonsApi } from "@/lib/lessons-api";
import { BAND_LABELS, BAND_ORDER } from "@/lib/stage-view";
import { StartingPoint } from "@/lib/starting-point";
import type { LessonDetail, QuizKind, QuizReview, ReviewQuestion } from "@/lib/types";
import { QuizNames } from "@/lib/quiz-names";
import { cn } from "@/lib/utils";

const NAME = { diagnostic: QuizNames.of("diagnostic"), prerequisite: QuizNames.of("prerequisite") } satisfies Record<QuizKind, string>;

/** The answered quick check (and foundations check), read-only: every question in one list with the learner's pick, the
 *  right answer and why. There are no inputs anywhere. */
export function QuickCheckAnswers({ lesson }: { lesson: Pick<LessonDetail, "id" | "results"> }) {
  const kinds = (["diagnostic", "prerequisite"] as const).filter((kind) => lesson.results[kind]);
  const [kind, setKind] = useState<QuizKind>(kinds[0] ?? "diagnostic");
  const [review, setReview] = useState<{ kind: QuizKind; data: QuizReview } | null>(null);
  // A failed load belongs to the check that failed: choosing the other one is a new try.
  const [failure, setFailure] = useState<{ kind: QuizKind; message: string } | null>(null);

  useEffect(() => {
    let active = true;
    lessonsApi
      .review(lesson.id, kind)
      .then((data) => active && setReview({ kind, data }))
      .catch((err) => active && setFailure({ kind, message: err instanceof ApiError ? err.message : "We couldn't load your answers." }));
    return () => {
      active = false;
    };
  }, [lesson.id, kind]);

  const data = review?.kind === kind ? review.data : null;
  const error = failure?.kind === kind ? failure.message : null;
  return (
    <div className="flex flex-col gap-5">
      {kinds.length > 1 && (
        <div role="group" aria-label="Which check" className="inline-flex self-start rounded-xl bg-muted p-1">
          {kinds.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={kind === option}
              onClick={() => setKind(option)}
              className={cn(
                "rounded-lg px-3 py-1.5 text-sm font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                kind === option ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {NAME[option]}
            </button>
          ))}
        </div>
      )}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : data ? (
        <Answers kind={kind} review={data} />
      ) : (
        <Skeleton className="h-72 rounded-[22px]" />
      )}
    </div>
  );
}

function Answers({ kind, review }: { kind: QuizKind; review: QuizReview }) {
  const bands = StartingPoint.bands(review.result, review);
  const taken = DateText.day(review.submitted_at);
  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-4 px-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-xs font-bold tracking-wider text-insight-text uppercase">
              {NAME[kind]}
              {taken && ` · taken ${taken}`}
            </p>
            <Badge variant="secondary">
              <LockIcon className="size-3" aria-hidden="true" /> Read-only
            </Badge>
          </div>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 className="font-heading text-2xl font-semibold tracking-tight">Your {NAME[kind].toLowerCase()} answers</h2>
            <p className="font-heading text-3xl font-semibold tabular-nums" aria-label={`${review.result.correct} out of ${review.result.total} correct`}>
              {AnswersView.score(review.result)}
            </p>
          </div>
          {bands.length > 0 && (
            <ul className="flex flex-col gap-1.5" aria-label="By difficulty">
              {bands.map((band) => (
                <li key={band.band} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">{band.label}</span>
                  <BandDots dots={band.dots} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <ol className="flex flex-col gap-4">
        {review.questions.map((question, index) => (
          <li key={question.id}>
            <QuestionAnswer question={question} number={index + 1} />
          </li>
        ))}
      </ol>
    </>
  );
}

function QuestionAnswer({ question, number }: { question: ReviewQuestion; number: number }) {
  const verdict = AnswersView.verdict(question);
  const level = question.band ? BAND_ORDER.indexOf(question.band) + 1 : 0;
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 px-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-bold text-insight-text">
            <span className="font-mono text-muted-foreground">{number}</span>
            {question.band && (
              <>
                <span role="img" aria-label={`Difficulty ${level} of ${BAND_ORDER.length}`} className="flex gap-1">
                  {BAND_ORDER.map((band, n) => (
                    <span key={band} className={cn("h-2 w-5 rounded-full", n < level ? "bg-insight" : "bg-insight-soft")} />
                  ))}
                </span>
                {BAND_LABELS[question.band]}
              </>
            )}
          </div>
          <Badge variant={AnswersView.badge(verdict.kind)}>{verdict.label}</Badge>
        </div>
        <p className="font-heading text-lg leading-snug font-medium whitespace-pre-wrap">{question.question}</p>
        <ul className="flex flex-col gap-2">
          {question.options.map((option, index) => {
            const mark = AnswersView.option(question, index);
            return (
              <li
                key={index}
                className={cn(
                  "flex items-center gap-3 rounded-xl border-2 px-3 py-2 text-sm",
                  mark.tone === "correct" && "border-success bg-success-soft text-success-text",
                  mark.tone === "wrong" && "border-marigold bg-marigold-soft text-marigold-text",
                  mark.tone === "plain" && "border-border text-muted-foreground",
                )}
              >
                <span className="grid size-6 shrink-0 place-items-center rounded-md bg-card/60 font-mono text-xs font-bold">{index + 1}</span>
                <span className="flex-1">{option}</span>
                {mark.tone === "correct" && (
                  <span className="flex items-center gap-1 text-xs font-extrabold">
                    <CheckIcon className="size-4" aria-hidden="true" /> {mark.picked ? "Your answer · right" : "Right answer"}
                  </span>
                )}
                {mark.tone === "wrong" && (
                  <span className="flex items-center gap-1 text-xs font-extrabold">
                    <XIcon className="size-4" aria-hidden="true" /> Your answer
                  </span>
                )}
              </li>
            );
          })}
        </ul>
        {question.answer === "dont_know" && (
          <p className="flex items-center gap-1.5 text-sm text-marigold-text">
            <MinusIcon className="size-4" aria-hidden="true" /> You didn&apos;t pick an option, and that&apos;s fine: it helps us teach you the right things.
          </p>
        )}
        {question.explanation && (
          <div className="flex flex-col gap-1 rounded-xl bg-insight-soft px-3 py-2.5 text-sm">
            <p className="text-xs font-extrabold text-insight-text">Why</p>
            <p>{question.explanation}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
