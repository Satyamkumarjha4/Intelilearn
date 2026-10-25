"use client";

import { CheckCircle2Icon, ChevronDownIcon, CircleDashedIcon, LockIcon, MinusCircleIcon, XCircleIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { DateText } from "@/lib/format";
import { lessonsApi } from "@/lib/lessons-api";
import { TestResultView } from "@/lib/test-session";
import { TestReport, type AnswerText, type Status } from "@/lib/test-report";
import type { LearnerTestQuestion, QuestionResult, QuestionType, TestSubmission } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;
const TYPE_TAG: Record<QuestionType, string> = {
  mcq: "Multiple choice",
  numerical: "Number",
  short_answer: "Short answer",
  long_answer: "Written answer",
  code: "Code",
};

type Props = {
  lessonId: string;
  lessonTitle: string;
  questions: LearnerTestQuestion[];
  /** The submission just made, if any (otherwise it is read from the server). */
  first?: TestSubmission | null;
  onOpenLesson: () => void;
};

/**
 * The submitted test, read-only: nothing here can be changed and nothing offers another go. While the written answers
 * are being marked it shows that (and asks again every few seconds); if that failed it says so and offers to mark again
 * on the answers already given.
 */
export function TestResults({ lessonId, lessonTitle, questions, first, onOpenLesson }: Props) {
  const [submission, setSubmission] = useState<TestSubmission | null>(first ?? null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [regrading, setRegrading] = useState(false);
  const grading = submission?.status === "grading";

  useEffect(() => {
    let active = true;
    const load = () =>
      lessonsApi
        .currentSubmission(lessonId)
        .then((data) => active && setSubmission(data))
        .catch(() => active && setLoadFailed(true));
    if (!submission) void load();
    const timer = grading ? setInterval(load, POLL_MS) : undefined;
    return () => {
      active = false;
      clearInterval(timer);
    };
    // Loading again is only about whether we have a submission and whether it is still being marked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonId, submission === null, grading]);

  if (!submission) {
    return loadFailed ? (
      <Alert variant="destructive">
        <AlertDescription>We couldn&apos;t load your test result. Please refresh the page.</AlertDescription>
      </Alert>
    ) : (
      <Skeleton className="h-72 rounded-[22px]" />
    );
  }

  const regrade = async () => {
    setRegrading(true);
    try {
      await lessonsApi.regradeTest(lessonId, submission.id);
      setSubmission({ ...submission, status: "grading", error: "" });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "We couldn't start marking again.");
    } finally {
      setRegrading(false);
    }
  };

  const card = submission.result;
  const when = DateText.day(submission.submitted_at);
  return (
    <div className="flex flex-col gap-5">
      <p className="flex items-start gap-2 rounded-xl border border-border bg-muted/50 px-3 py-2.5 text-sm text-muted-foreground">
        <LockIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>
          <strong className="text-foreground">Your test is final.</strong> Your answers, score and suggestions are saved and can&apos;t be changed.
          {when && ` Submitted ${when}.`}
        </span>
      </p>

      {grading && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 px-6 py-6 text-center" aria-live="polite">
            <CircleDashedIcon className="size-9 text-primary motion-safe:animate-spin" aria-hidden="true" />
            <h2 className="font-heading text-2xl font-semibold">Marking your test</h2>
            <p className="text-muted-foreground">The written answers take a little longer. You can leave this page; the result will be here.</p>
          </CardContent>
        </Card>
      )}

      {submission.status === "failed" && (
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

      {card && submission.status === "graded" && <Hero card={card} />}
      {card && submission.status === "graded" && card.topics_to_revisit.length > 0 && (
        <Revisit topics={card.topics_to_revisit} lessonTitle={lessonTitle} />
      )}
      {card && (
        <QuestionList rows={card.questions} questions={questions} answers={submission.answers} />
      )}

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

function Hero({ card }: { card: NonNullable<TestSubmission["result"]> }) {
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

function Revisit({ topics, lessonTitle }: { topics: string[]; lessonTitle: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const start = async (topic: string) => {
    setBusy(topic);
    const { topic: name, context } = TestReport.followUp(lessonTitle, topic);
    try {
      const { lesson_id } = await lessonsApi.create(name, context);
      router.push(`/lessons/${lesson_id}`);
    } catch (err) {
      toast.error(TestReport.followUpError(err instanceof ApiError ? err.status : undefined));
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
                  {row.type !== "mcq" && <Badge variant="secondary" className="hidden sm:inline-flex">{TYPE_TAG[row.type]}</Badge>}
                  <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">{TestResultView.label(row)}</span>
                  <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground motion-safe:transition-transform group-open:rotate-180" aria-hidden="true" />
                </summary>
                <div className="flex flex-col gap-3 border-t border-dashed border-border px-4 py-3 text-sm">
                  {question && <Markdown className="text-base">{question.question}</Markdown>}
                  <Answer label="Your answer" answer={yours} empty="You didn't answer this one." />
                  {correct && <Answer label="Correct answer" answer={correct} />}
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
