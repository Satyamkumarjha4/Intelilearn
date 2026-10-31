"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useState } from "react";
import { toast } from "sonner";

import { CalibrationRunner } from "@/components/quizzes/calibration-runner";
import { QuizBuilding } from "@/components/quizzes/quiz-building";
import { QuizTaker } from "@/components/quizzes/quiz-taker";
import { useQuiz } from "@/components/quizzes/use-quiz";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { QuizStageView } from "@/lib/quiz-stage-view";
import { quizzesApi } from "@/lib/quizzes-api";

export default function QuizPage({ params }: PageProps<"/quizzes/[id]">) {
  const { id } = use(params);
  const router = useRouter();
  const { quiz, error, refresh, nodeStatus } = useQuiz(id);
  const [stopping, setStopping] = useState(false);

  if (error === "not_found") {
    return (
      <Shell>
        <Card>
          <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
            <h1 className="font-heading text-2xl font-semibold">We can&apos;t find that quiz</h1>
            <p className="text-muted-foreground">It may have been deleted.</p>
            <Link href="/quizzes" className={buttonVariants()}>
              Back to my quizzes
            </Link>
          </CardContent>
        </Card>
      </Shell>
    );
  }
  if (error) {
    return (
      <Shell>
        <Card>
          <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
            <p className="text-muted-foreground">{error}</p>
            <Button variant="outline" onClick={() => void refresh()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      </Shell>
    );
  }
  if (!quiz) {
    return (
      <Shell>
        <Skeleton className="h-72 rounded-[22px]" aria-label="Loading your quiz" />
      </Shell>
    );
  }

  const view = QuizStageView.of(quiz);
  const stop = async () => {
    if (!quiz.run_id) return;
    setStopping(true);
    try {
      await quizzesApi.cancelRun(quiz.run_id);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "We couldn't stop that.");
    } finally {
      setStopping(false);
    }
  };
  const remove = async () => {
    try {
      await quizzesApi.remove(quiz.id);
      router.push("/quizzes");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "We couldn't delete the quiz.");
    }
  };

  return (
    <Shell>
      <header className="flex flex-col gap-1">
        <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">Quick quiz</p>
        <h1 className="font-heading text-3xl font-semibold tracking-tight">{quiz.topic}</h1>
        <p className="text-sm text-muted-foreground">{QuizStageView.facts(quiz)}</p>
      </header>

      {view.kind === "building" && <QuizBuilding nodeStatus={nodeStatus} onCancel={quiz.run_id ? () => void stop() : undefined} cancelling={stopping} />}
      {view.kind === "calibration" && <CalibrationRunner quizId={quiz.id} onFinished={() => void refresh()} />}
      {view.kind === "failed" && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
            <h2 className="font-heading text-2xl font-semibold">We couldn&apos;t make this quiz</h2>
            <p className="max-w-prose text-muted-foreground">{view.message}</p>
            <div className="flex flex-wrap justify-center gap-3">
              <Link href="/quizzes/new" className={buttonVariants({ variant: "marigold" })}>
                Start again
              </Link>
              <Button variant="outline" onClick={() => void remove()}>
                Delete this quiz
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {(view.kind === "taking" || view.kind === "preparing" || view.kind === "results") && <QuizTaker quiz={quiz} onChanged={() => void refresh()} />}
      {view.kind === "empty" && <p className="text-muted-foreground">This quiz has no tries yet.</p>}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 px-4 py-8">
      <Link href="/quizzes" className={buttonVariants({ variant: "ghost", size: "sm", className: "self-start" })}>
        <ArrowLeftIcon /> My quizzes
      </Link>
      {children}
    </main>
  );
}
