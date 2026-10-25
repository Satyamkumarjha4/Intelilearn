"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { toast } from "sonner";

import { MasteryChoice } from "@/components/lessons/mastery-choice";
import { PipelineProgress } from "@/components/lessons/pipeline-progress";
import { QuizResultCard } from "@/components/lessons/quiz-result-card";
import { QuizRunner } from "@/components/lessons/quiz-runner";
import { ResultsSummary } from "@/components/lessons/results-summary";
import { StudyMaterialView } from "@/components/lessons/study-material-view";
import { StageBadge } from "@/components/lessons/stage-badge";
import { useLesson } from "@/components/lessons/use-lesson";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants, Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { StageView } from "@/lib/stage-view";
import type { QuizKind, QuizResultSummary } from "@/lib/types";

const PROGRESS_TITLES = {
  preparing_diagnostic: "Preparing your quiz",
  generating_material: "Writing your study sheet",
  generating_lesson: "Building your lesson",
} as const;

export default function LessonPage({ params }: PageProps<"/lessons/[id]">) {
  const { id } = use(params);
  const { lesson, error, refresh, pipeline } = useLesson(id);
  const [submitted, setSubmitted] = useState<{ kind: QuizKind; result: QuizResultSummary } | null>(null);

  if (error === "not_found") {
    return (
      <Shell>
        <Alert>
          <AlertTitle>Lesson not found</AlertTitle>
          <AlertDescription>It may have been deleted.</AlertDescription>
        </Alert>
      </Shell>
    );
  }
  if (error && !lesson) {
    return (
      <Shell>
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </Shell>
    );
  }
  if (!lesson) return <Shell><div className="h-64" aria-busy="true" /></Shell>;

  const screen = StageView.of(lesson);
  const waitingForQuiz = screen === "diagnostic" || screen === "prerequisite";
  const justSubmitted = submitted && waitingForQuiz && submitted.kind === screen ? submitted : null;

  const retry = async () => {
    try {
      await lessonsApi.retry(id);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not retry.");
    }
  };
  const cancel = async () => {
    if (!lesson.active_run_id) return;
    try {
      await lessonsApi.cancelRun(lesson.active_run_id);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not cancel.");
    }
  };

  return (
    <Shell>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-semibold tracking-tight">{lesson.title || lesson.topic}</h2>
        <StageBadge stage={lesson.stage} />
      </header>

      <ResultsSummary lesson={lesson} skip={justSubmitted?.kind} />

      {justSubmitted ? (
        <>
          <QuizResultCard result={justSubmitted.result} level={lesson.level} />
          <p className="text-sm text-muted-foreground" aria-live="polite">
            Working out your next step…
          </p>
        </>
      ) : waitingForQuiz ? (
        <QuizRunner
          key={screen}
          lessonId={lesson.id}
          kind={screen}
          onSubmitted={(result) => {
            setSubmitted({ kind: screen, result });
            void refresh();
          }}
        />
      ) : screen === "progress" ? (
        <PipelineProgress
          pipeline={pipeline}
          title={PROGRESS_TITLES[lesson.stage as keyof typeof PROGRESS_TITLES] ?? "Working on your lesson"}
          onCancel={lesson.active_run_id ? cancel : undefined}
        />
      ) : screen === "failed" ? (
        <Card>
          <CardHeader>
            <CardTitle>This lesson stopped</CardTitle>
            <CardDescription>Nothing is lost. Retrying continues from the last saved step.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Alert variant="destructive">
              <AlertDescription>{lesson.error || "Something went wrong."}</AlertDescription>
            </Alert>
            <Button className="self-start" onClick={retry}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : screen === "choice" ? (
        <MasteryChoice lessonId={lesson.id} result={lesson.results.diagnostic} onChosen={() => void refresh()} />
      ) : screen === "material" ? (
        <StudyMaterialView lesson={lesson} pipeline={pipeline} onRequested={() => void refresh()} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Your lesson</CardTitle>
            <CardDescription>This part of the app is arriving in a later update.</CardDescription>
          </CardHeader>
        </Card>
      )}

      {lesson.warnings.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          {lesson.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <Link href="/lessons" className={buttonVariants({ variant: "ghost", size: "sm", className: "self-start" })}>
        <ArrowLeftIcon /> All lessons
      </Link>
      {children}
    </main>
  );
}
