"use client";

import { CompassIcon, WifiOffIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useState } from "react";
import { toast } from "sonner";

import { FailedCard } from "@/components/lessons/failed-card";
import { LessonHeader } from "@/components/lessons/lesson-header";
import { LessonTabBar } from "@/components/lessons/lesson-tab-bar";
import { LessonViewer } from "@/components/lessons/lesson-viewer";
import { MasteryChoice } from "@/components/lessons/mastery-choice";
import { PipelineProgress } from "@/components/lessons/pipeline-progress";
import { QuickCheck } from "@/components/lessons/quick-check";
import { QuickCheckAnswers } from "@/components/lessons/quick-check-answers";
import { QuickCheckDone } from "@/components/lessons/quick-check-done";
import { ResultsSummary } from "@/components/lessons/results-summary";
import { SmallNotes } from "@/components/lessons/small-notes";
import { StartingPointCard } from "@/components/lessons/starting-point-card";
import { StudyMaterialView } from "@/components/lessons/study-material-view";
import { TestTabPanel } from "@/components/lessons/test-tab-panel";
import { useDiagnosticReview } from "@/components/lessons/use-diagnostic-review";
import { useLesson } from "@/components/lessons/use-lesson";
import { StatusCard } from "@/components/status-card";
import { Button, buttonVariants } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { LessonTabs, type TabId } from "@/lib/lesson-tabs";
import { PlainWarning } from "@/lib/plain-notes";
import { StageView } from "@/lib/stage-view";
import type { QuizKind, QuizResultSummary, Stage } from "@/lib/types";
import { cn } from "@/lib/utils";

import Loading from "./loading";

const BUILDING_TITLES: Partial<Record<Stage, string>> = {
  preparing_diagnostic: "Getting your quick check ready",
  generating_material: "Building your study sheet",
  generating_lesson: "Building your lesson",
};

/** The small line above the heading: the foundations check has its own words while it is being prepared. */
function buildingTitle(stage: Stage, route: string): string {
  if (stage === "preparing_diagnostic" && route === "prerequisite") return "Preparing your foundations check";
  return BUILDING_TITLES[stage] ?? "Working on your lesson";
}

export default function LessonPage({ params }: PageProps<"/lessons/[id]">) {
  const { id } = use(params);
  // `useSearchParams` (the open tab lives in the address) needs a Suspense boundary above it.
  return (
    <Suspense fallback={<Loading />}>
      <Workspace id={id} />
    </Suspense>
  );
}

function Workspace({ id }: { id: string }) {
  const { lesson, error, refresh, pipeline } = useLesson(id);
  const [submitted, setSubmitted] = useState<{ kind: QuizKind; result: QuizResultSummary } | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const review = useDiagnosticReview(id, Boolean(lesson?.assessment && lesson.results.diagnostic));

  if (error === "not_found") {
    return (
      <Shell>
        <StatusCard
          icon={CompassIcon}
          title="We couldn't find this lesson"
          actions={
            <Link href="/lessons" className={buttonVariants()}>
              Back to my lessons
            </Link>
          }
        >
          <p>It may have been deleted.</p>
        </StatusCard>
      </Shell>
    );
  }
  if (error && !lesson) {
    return (
      <Shell>
        <StatusCard
          icon={WifiOffIcon}
          tone="destructive"
          title="We couldn't load this lesson"
          actions={
            <>
              <Button onClick={() => void refresh()}>Try again</Button>
              <Link href="/lessons" className={buttonVariants({ variant: "outline" })}>
                Back to my lessons
              </Link>
            </>
          }
        >
          <p>Check your connection and try again.</p>
        </StatusCard>
      </Shell>
    );
  }
  if (!lesson) return <Loading />;

  const ready = lesson.stage === "ready";
  const screen = StageView.of(lesson);
  const waitingForQuiz = screen === "diagnostic" || screen === "prerequisite";
  const justSubmitted = submitted && waitingForQuiz && submitted.kind === screen ? submitted : null;
  const tabs = LessonTabs.of(lesson);
  const activeTab = LessonTabs.pick(tabs, searchParams.get("tab"));
  const building = !ready && screen === "progress";

  const selectTab = (tab: TabId) => router.replace(`${pathname}?tab=${tab}`, { scroll: false });
  const retry = async () => {
    try {
      await lessonsApi.retry(id);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not retry.");
    }
  };
  const stop = async () => {
    if (!lesson.active_run_id) return;
    try {
      await lessonsApi.cancelRun(lesson.active_run_id);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not stop building.");
    }
  };

  const panels: Record<TabId, React.ReactNode> = {
    lesson:
      lesson.route === "mastery" ? (
        <StudyMaterialView lesson={lesson} pipeline={pipeline} onRequested={refresh} />
      ) : (
        <LessonViewer lessonId={lesson.id} testStatus={lesson.test_status} onGoToTest={() => selectTab("test")} />
      ),
    test: <TestTabPanel lessonId={lesson.id} lessonTitle={lesson.title || lesson.topic} onChanged={() => void refresh()} onOpenLesson={() => selectTab("lesson")} />,
    answers: lesson.results.diagnostic || lesson.results.prerequisite ? (
      <QuickCheckAnswers lesson={lesson} />
    ) : (
      <p className="text-muted-foreground">Your quick check answers will show up here.</p>
    ),
  };

  return (
    <Shell>
      <LessonHeader lesson={lesson} />

      {activeTab ? (
        <LessonTabBar tabs={tabs} active={activeTab} onChange={selectTab} panels={panels} />
      ) : (
        <>
          {screen === "failed" && <FailedCard error={lesson.error} onRetry={retry} />}
          {!building && <ResultsSummary lesson={lesson} skip={screen === "choice" ? "diagnostic" : justSubmitted?.kind} />}

          {justSubmitted ? (
            <QuickCheckDone kind={justSubmitted.kind} state="sent" />
          ) : waitingForQuiz ? (
            <QuickCheck
              key={screen}
              lessonId={lesson.id}
              kind={screen}
              onSubmitted={(result) => {
                setSubmitted({ kind: screen, result });
                void refresh();
              }}
              onAlreadyAttempted={() => {
                void refresh();
                if (lesson.stage === "ready") selectTab("answers"); // the answers are read-only now
              }}
            />
          ) : building ? (
            // The progress card stays in view (sticky) while the taller starting-point card scrolls; on a phone they stack.
            <div className={cn("grid items-start gap-6", lesson.assessment && "min-[900px]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]")}>
              <PipelineProgress
                className="min-[900px]:sticky min-[900px]:top-[calc(1rem+env(safe-area-inset-top))]"
                pipeline={pipeline}
                title={buildingTitle(lesson.stage, lesson.route)}
                onCancel={lesson.active_run_id ? stop : undefined}
              />
              {lesson.assessment && <StartingPointCard assessment={lesson.assessment} result={lesson.results.diagnostic} review={review} />}
            </div>
          ) : screen === "choice" ? (
            <MasteryChoice lessonId={lesson.id} result={lesson.results.diagnostic} onChosen={() => void refresh()} />
          ) : null}
        </>
      )}

      <SmallNotes notes={PlainWarning.all(lesson.warnings)} />
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 py-6">{children}</main>;
}
