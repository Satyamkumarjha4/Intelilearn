"use client";

import { CheckCircle2Icon, ChevronDownIcon, CircleDashedIcon, MinusCircleIcon, RotateCcwIcon, XCircleIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AttemptHistory } from "@/components/lessons/attempt-history";
import { FollowupDialog } from "@/components/lessons/followup-dialog";
import { FollowupOfferCard } from "@/components/lessons/followup-offer-card";
import { ApiError } from "@/lib/api";
import { AttemptHistoryView } from "@/lib/attempt-history";
import { FollowupOffers } from "@/lib/followup-offer";
import { DateText } from "@/lib/format";
import { lessonsApi } from "@/lib/lessons-api";
import { TestResultView } from "@/lib/test-session";
import { TestReport, type AnswerText, type Status } from "@/lib/test-report";
import { QuestionInputs } from "@/lib/question-inputs";
import type { AttemptHistory as History, LearnerTestQuestion, QuestionResult, TestSubmission } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

type Props = {
  lessonId: string;
  lessonTitle: string;
  /** The attempt on show: just handed in, or chosen from the history. */
  attempt: TestSubmission;
  history: History | null;
  /** The result was just handed in (not chosen from the history): an offer that comes with it opens as a pop-up. */
  fresh?: boolean;
  /** Asking for another try is on its way. */
  trying: boolean;
  onTryAgain: () => void;
  onSelect: (attemptId: string) => void;
  onOpenLesson: () => void;
};

/**
 * One attempt's result, read-only: its answers and score cannot change, but the learner can always try again with new
 * questions. While a written answer of an older lesson is being marked it shows that (and asks again every few
 * seconds); if that failed it says so and offers to mark again on the answers already given. Below, the history of
 * every try.
 */
export function TestResults({ lessonId, lessonTitle, attempt: shown, history, fresh = false, trying, onTryAgain, onSelect, onOpenLesson }: Props) {
  const [attempt, setAttempt] = useState<TestSubmission>(shown);
  const offer = attempt.status === "graded" ? FollowupOffers.parse(attempt.followup) : null;
  const [dialogOpen, setDialogOpen] = useState(fresh && offer !== null && FollowupOffers.view(offer).surface === "dialog");
  const [regrading, setRegrading] = useState(false);
  const grading = attempt.status === "grading";

  useEffect(() => {
    if (!grading) return;
    let active = true;
    const timer = setInterval(() => {
      lessonsApi
        .attempt(lessonId, attempt.id)
        .then((data) => active && setAttempt(data))
        .catch(() => undefined);
    }, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [lessonId, attempt.id, grading]);

  const regrade = async () => {
    setRegrading(true);
    try {
      await lessonsApi.regradeAttempt(lessonId, attempt.id);
      setAttempt({ ...attempt, status: "grading", error: "" });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "We couldn't start marking again.");
    } finally {
      setRegrading(false);
    }
  };

  const card = attempt.result;
  const row = history ? AttemptHistoryView.rows(history).find((r) => r.attemptNo === attempt.attempt_no) : undefined;
  const facts = [
    `Attempt ${attempt.attempt_no}`,
    attempt.submitted_at ? DateText.day(attempt.submitted_at) : "",
    AttemptHistoryView.duration(attempt.duration_s) && `took ${AttemptHistoryView.duration(attempt.duration_s)}`,
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-muted-foreground">{facts.join(" · ")}</p>

      {grading && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 px-6 py-6 text-center" aria-live="polite">
            <CircleDashedIcon className="size-9 text-primary motion-safe:animate-spin" aria-hidden="true" />
            <h2 className="font-heading text-2xl font-semibold">Marking your test</h2>
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

      {card && attempt.status === "graded" && <Hero card={card} changes={row?.changes ?? []} />}
      {offer && <FollowupOfferCard lessonId={lessonId} offer={offer} />}
      {offer && FollowupOffers.view(offer).surface === "dialog" && (
        <FollowupDialog lessonId={lessonId} offer={offer} open={dialogOpen} onOpenChange={setDialogOpen} />
      )}
      {attempt.status === "graded" && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3">
            <p className="max-w-prose text-sm text-muted-foreground">Want a better score? Try again with new questions. Your best result is kept.</p>
            <Button variant="marigold" onClick={onTryAgain} disabled={trying}>
              <RotateCcwIcon className="size-4" aria-hidden="true" />
              {trying ? "Getting ready…" : "Try again"}
            </Button>
          </CardContent>
        </Card>
      )}
      {card && attempt.status === "graded" && card.topics_to_revisit.length > 0 && (
        <Revisit topics={card.topics_to_revisit} lessonTitle={lessonTitle} attemptId={attempt.id} />
      )}
      {history && history.attempts.length > 1 && <AttemptHistory history={history} selectedId={attempt.id} onSelect={onSelect} />}
      {card && <QuestionList rows={card.questions} questions={attempt.questions} answers={attempt.answers} />}

      <div className="flex flex-wrap gap-3">
        <Button variant="outline" onClick={onOpenLesson}>
          Review the lesson
        </Button>
        <Link href="/lessons" className={buttonVariants({ variant: "ghost" })}>
          Back to my lessons
        </Link>
      </div>
    </div>
  );
}

function Hero({ card, changes }: { card: NonNullable<TestSubmission["result"]>; changes: string[] }) {
  const { percent, awarded, available } = card.score;
  const stats = TestReport.stats(card.questions);
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-5 px-6 py-6 sm:flex-row sm:gap-8">
        <div className="relative size-36 shrink-0" role="img" aria-label={`${percent} percent: ${awarded} of ${available} marks`}>
          <svg viewBox="0 0 128 128" className="size-full -rotate-90">
            <circle cx="64" cy="64" r={radius} fill="none" strokeWidth="12" className="stroke-success-soft" />
            <circle
              cx="64" cy="64" r={radius} fill="none" strokeWidth="12" strokeLinecap="round"
              className="stroke-success motion-safe:transition-[stroke-dashoffset]"
              strokeDasharray={circumference}
              strokeDashoffset={circumference * (1 - Math.min(Math.max(percent, 0), 100) / 100)}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-heading text-3xl font-semibold tabular-nums">{percent}%</span>
            <span className="text-xs text-muted-foreground">
              {awarded} of {available} marks
            </span>
          </div>
        </div>
        <div className="flex flex-col items-center gap-3 text-center sm:items-start sm:text-left">
          <h2 className="font-heading text-2xl font-semibold tracking-tight">{TestReport.headline(percent)}</h2>
          {changes.length > 0 && <p className="text-sm font-semibold text-muted-foreground">{changes.join(" · ")}</p>}
          <ul className="flex flex-wrap justify-center gap-2 sm:justify-start">
            <li><Badge variant="success">{stats.correct} correct</Badge></li>
            {stats.partial > 0 && <li><Badge variant="marigold">{stats.partial} partly right</Badge></li>}
            <li><Badge variant="destructive-soft">{stats.missed} missed</Badge></li>
            {stats.aiGraded > 0 && (
              <li><Badge variant="insight">{stats.aiGraded} written {stats.aiGraded === 1 ? "answer" : "answers"} graded by AI</Badge></li>
            )}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

function Revisit({ topics, lessonTitle, attemptId }: { topics: string[]; lessonTitle: string; attemptId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const start = async (topic: string) => {
    setBusy(topic);
    const { topic: name, context } = TestReport.followUp(lessonTitle, topic);
    try {
      // The server checks that this attempt is yours and listed this topic; it is how a lesson is marked as recommended.
      const { lesson_id } = await lessonsApi.create(name, context, { recommendedFrom: { attemptId, topic } });
      router.push(`/lessons/${lesson_id}`);
    } catch (err) {
      toast.error(TestReport.followUpMessage(err));
      setBusy(null);
    }
  };
  return (
    <section aria-labelledby="revisit-heading" className="flex flex-col gap-3">
      <h2 id="revisit-heading" className="font-heading text-xl font-semibold">Worth another look</h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {topics.map((topic) => (
          <li key={topic}>
            <Card size="sm" className="h-full">
              <CardContent className="flex h-full flex-col items-start justify-between gap-3">
                <p className="font-semibold">{topic}</p>
                <Button variant="marigold" size="sm" disabled={busy !== null} onClick={() => start(topic)}>
                  {busy === topic ? "Starting…" : "Make a lesson on this"}
                </Button>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

const ICON: Record<Status, React.ReactNode> = {
  right: <CheckCircle2Icon className="size-5 text-success" aria-label="Right" />,
  partial: <MinusCircleIcon className="size-5 text-marigold-deep" aria-label="Partly right" />,
  wrong: <XCircleIcon className="size-5 text-destructive" aria-label="Missed" />,
  pending: <CircleDashedIcon className="size-5 text-muted-foreground" aria-label="Being marked" />,
};

function QuestionList({ rows, questions, answers }: { rows: QuestionResult[]; questions: LearnerTestQuestion[]; answers: Record<string, unknown> }) {
  const byId = new Map(questions.map((q) => [q.id, q]));
  return (
    <section aria-labelledby="questions-heading" className="flex flex-col gap-3">
      <h2 id="questions-heading" className="font-heading text-xl font-semibold">Question by question</h2>
      <ol className="flex flex-col gap-2">
        {rows.map((row, index) => {
          const question = byId.get(row.id);
          const status = TestReport.status(row);
          const yours = question ? TestReport.yourAnswer(question, answers[row.id]) : null;
          const correct = question && status !== "right" ? TestReport.correctAnswer(question, row.solution) : null;
          return (
            <li key={row.id}>
              <details className="group rounded-2xl border-[1.5px] border-border bg-card open:shadow-card">
                <summary className="flex cursor-pointer list-none items-center gap-3 rounded-2xl px-4 py-3 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
                  {ICON[status]}
                  <span className="min-w-0 flex-1">
                    <span className="mr-2 font-mono text-xs text-muted-foreground">{index + 1}</span>
                    <span className="line-clamp-2 font-semibold">{question?.question ?? row.concept}</span>
                  </span>
                  {row.type !== "mcq" && <Badge variant="secondary" className="hidden sm:inline-flex">{QuestionInputs.of(row.type).label}</Badge>}
                  <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">{TestResultView.label(row)}</span>
                  <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground motion-safe:transition-transform group-open:rotate-180" aria-hidden="true" />
                </summary>
                <div className="flex flex-col gap-3 border-t border-dashed border-border px-4 py-3 text-sm">
                  {question && <Markdown className="text-base">{question.question}</Markdown>}
                  <Answer label="Your answer" answer={yours} empty="You didn't answer this one." />
                  {correct && <Answer label={question?.type === "msq" ? "Correct answers" : "Correct answer"} answer={correct} />}
                  {TestReport.criteria(row).length > 0 && (
                    <div className="flex flex-col gap-1">
                      <p className="text-xs font-extrabold text-muted-foreground">What it was marked on</p>
                      <ul className="flex flex-col gap-1">
                        {TestReport.criteria(row).map((criterion) => (
                          <li key={criterion.text} className="flex items-start justify-between gap-3">
                            <span>{criterion.text}</span>
                            <span className={cn("font-mono text-xs whitespace-nowrap", criterion.full ? "text-success-text" : "text-muted-foreground")}>{criterion.earned}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {row.feedback && (
                    <div className="flex flex-col gap-1 rounded-xl bg-insight-soft px-3 py-2.5">
                      <p className="text-xs font-extrabold text-insight-text">Feedback{TestResultView.source(row) === "Graded by AI" ? " · graded by AI" : ""}</p>
                      <p>{row.feedback}</p>
                    </div>
                  )}
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Answer({ label, answer, empty }: { label: string; answer: AnswerText | null; empty?: string }) {
  if (!answer && !empty) return null;
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-extrabold text-muted-foreground">{label}</p>
      {answer ? (
        <p className={cn("whitespace-pre-wrap", answer.code && "overflow-x-auto rounded-lg bg-muted p-2 font-mono text-xs")}>{answer.text}</p>
      ) : (
        <p className="text-muted-foreground italic">{empty}</p>
      )}
    </div>
  );
}
