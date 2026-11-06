"use client";

import { CircleDashedIcon, RotateCcwIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { CostLabel } from "@/components/credits/cost-label";
import { AttemptHistory } from "@/components/lessons/attempt-history";
import { QuestionBreakdown, ScoreHero } from "@/components/lessons/result-parts";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AttemptHistoryView } from "@/lib/attempt-history";
import { CostSizes } from "@/lib/credits/cost-sizes";
import { DateText } from "@/lib/format";
import { QuizMessages } from "@/lib/quiz-messages";
import { QuizResults } from "@/lib/quiz-results";
import { quizzesApi } from "@/lib/quizzes-api";
import type { QuizAttempt, QuizDetail } from "@/lib/types";

const POLL_MS = 3000;

type Props = {
  quiz: QuizDetail;
  /** The attempt on show: just handed in, or chosen from the history. */
  attempt: QuizAttempt;
  trying: boolean;
  onTryAgain: () => void;
  onSelect: (attemptId: string) => void;
  onCreateLesson: (attemptId: string) => Promise<void>;
};

/**
 * One try's result, read-only: the score, what to do next ("Create a lesson for this" for a quiz about a topic, the
 * lessons to study for one made from lessons), a button to try again with new questions, the history of tries (compared
 * with this quiz's own only) and every question with the answer and the marks.
 */
export function QuizResult({ quiz, attempt: shown, trying, onTryAgain, onSelect, onCreateLesson }: Props) {
  const [attempt, setAttempt] = useState<QuizAttempt>(shown);
  const [regrading, setRegrading] = useState(false);
  const [making, setMaking] = useState(false);
  const grading = attempt.status === "grading";

  useEffect(() => {
    if (!grading) return;
    let active = true;
    const timer = setInterval(() => {
      quizzesApi
        .attempt(quiz.id, attempt.id)
        .then((data) => active && setAttempt(data))
        .catch(() => undefined);
    }, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [quiz.id, attempt.id, grading]);

  const regrade = async () => {
    setRegrading(true);
    try {
      await quizzesApi.regradeAttempt(quiz.id, attempt.id);
      setAttempt({ ...attempt, status: "grading", error: "" });
    } catch (err) {
      toast.error(QuizMessages.retake(err));
    } finally {
      setRegrading(false);
    }
  };

  const createLesson = async () => {
    setMaking(true);
    try {
      await onCreateLesson(attempt.id);
    } catch (err) {
      toast.error(QuizMessages.createLesson(err));
      setMaking(false);
    }
  };

  const card = attempt.result;
  const advice = QuizResults.advice(quiz, attempt);
  const row = AttemptHistoryView.rows({ attempts: quiz.attempts, trend: quiz.trend }).find((r) => r.attemptNo === attempt.attempt_no);
  const facts = [
    `Try ${attempt.attempt_no}`,
    attempt.submitted_at ? DateText.day(attempt.submitted_at) : "",
    AttemptHistoryView.duration(attempt.duration_s) && `took ${AttemptHistoryView.duration(attempt.duration_s)}`,
    QuizResults.marks(attempt),
  ].filter(Boolean);

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-muted-foreground">{facts.join(" · ")}</p>

      {grading && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 px-6 py-6 text-center" aria-live="polite">
            <CircleDashedIcon className="size-9 text-primary motion-safe:animate-spin" aria-hidden="true" />
            <h2 className="font-heading text-2xl font-semibold">Marking your quiz</h2>
            <p className="text-muted-foreground">The written answers take a little longer. You can leave this page; the result will be here.</p>
          </CardContent>
        </Card>
      )}

      {attempt.status === "failed" && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 px-6 py-6 text-center">
            <h2 className="font-heading text-2xl font-semibold">We couldn&apos;t mark your written answers</h2>
            <p className="text-muted-foreground">That&apos;s a problem on our side, not yours. Your answers are safe, and what could be marked straight away is below.</p>
            <Button variant="marigold" onClick={regrade} disabled={regrading}>
              {regrading ? "Starting…" : "Try marking again"}
            </Button>
          </CardContent>
        </Card>
      )}

      {card && attempt.status === "graded" && <ScoreHero card={card} changes={row?.changes ?? []} />}

      {advice.kind === "topic" && advice.canCreateLesson && (
        <Card className="border-primary bg-primary-soft">
          <CardContent className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex max-w-prose flex-col gap-1">
              <p className="font-heading text-lg font-semibold">{QuizResults.CREATE_LESSON}</p>
              <p className="text-sm text-muted-foreground">
                {advice.topics.length > 0 ? `You could work on ${advice.topics.slice(0, 3).join(", ")}. ` : ""}
                {QuizResults.CREATE_HINT}
              </p>
            </div>
            <div className="flex flex-col items-start gap-1.5">
              <CostLabel ask={CostSizes.lessonFromQuiz()} />
              <Button onClick={() => void createLesson()} disabled={making}>
                <SparklesIcon aria-hidden="true" /> {making ? "Starting…" : QuizResults.CREATE_LESSON}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {advice.kind === "lessons" && advice.items.length > 0 && (
        <section aria-labelledby="study-heading" className="flex flex-col gap-3">
          <h2 id="study-heading" className="font-heading text-xl font-semibold">Worth another look</h2>
          <ul className="grid gap-3 sm:grid-cols-2">
            {advice.items.map((item) => (
              <li key={item.title}>
                <Card size="sm" className="h-full">
                  <CardContent className="flex h-full flex-col items-start gap-3">
                    <p className="font-semibold">{QuizResults.lessonLine(item)}</p>
                    {item.deleted ? (
                      <p className="text-sm text-muted-foreground">This lesson has been deleted, so there is nothing to open. You could make a new one from the home page.</p>
                    ) : (
                      <ul className="flex w-full flex-col gap-3">
                        {item.links.map((link) => (
                          <li key={link.concept} className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex min-w-0 flex-col">
                              <span className="font-medium">{link.concept}</span>
                              {link.where && <span className="text-xs text-muted-foreground">{link.where}</span>}
                            </div>
                            <Link href={link.href} className={buttonVariants({ variant: "marigold", size: "sm" })}>
                              {link.button}
                              <span className="sr-only"> for {link.concept}</span>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      {attempt.status === "graded" && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex max-w-prose flex-col gap-1.5">
              <p className="text-sm text-muted-foreground">{QuizResults.RETAKE_NOTE}</p>
              <CostLabel ask={CostSizes.quizRetake(quiz.config.num_questions, quiz.source_type)} />
            </div>
            <Button variant="marigold" onClick={onTryAgain} disabled={trying}>
              <RotateCcwIcon className="size-4" aria-hidden="true" />
              {trying ? "Getting ready…" : QuizResults.RETAKE}
            </Button>
          </CardContent>
        </Card>
      )}

      {quiz.attempts.length > 1 && <AttemptHistory history={{ attempts: quiz.attempts, trend: quiz.trend }} selectedId={attempt.id} onSelect={onSelect} />}
      {card && <QuestionBreakdown rows={card.questions} questions={attempt.questions} answers={attempt.answers} />}

      <div className="flex flex-wrap gap-3">
        <Link href="/quizzes" className={buttonVariants({ variant: "ghost" })}>
          Back to my quizzes
        </Link>
      </div>
    </div>
  );
}
