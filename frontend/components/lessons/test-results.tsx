"use client";

import { CircleDashedIcon, RotateCcwIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AttemptHistory } from "@/components/lessons/attempt-history";
import { FollowupDialog } from "@/components/lessons/followup-dialog";
import { FollowupOfferCard } from "@/components/lessons/followup-offer-card";
import { QuestionBreakdown, ScoreHero } from "@/components/lessons/result-parts";
import { ApiError } from "@/lib/api";
import { AttemptHistoryView } from "@/lib/attempt-history";
import { FollowupOffers } from "@/lib/followup-offer";
import { DateText } from "@/lib/format";
import { lessonsApi } from "@/lib/lessons-api";
import { TestReport } from "@/lib/test-report";
import type { AttemptHistory as History, TestSubmission } from "@/lib/types";

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

      {card && attempt.status === "graded" && <ScoreHero card={card} changes={row?.changes ?? []} />}
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
      {card && <QuestionBreakdown rows={card.questions} questions={attempt.questions} answers={attempt.answers} />}

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

