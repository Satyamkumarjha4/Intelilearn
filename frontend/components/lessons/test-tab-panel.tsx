"use client";

import { useEffect, useState } from "react";

import { TestResults } from "@/components/lessons/test-results";
import { TestRunner } from "@/components/lessons/test-runner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import type { LearnerTest, TestSubmission } from "@/lib/types";

type Props = { lessonId: string; lessonTitle: string; onChanged: () => void; onOpenLesson: () => void };

/** The Test tab: the final test as a deck of cards, or, once it has been submitted (now, or on an earlier visit), the
 *  result. A submitted test is never shown as a deck again. */
export function TestTabPanel({ lessonId, lessonTitle, onChanged, onOpenLesson }: Props) {
  const [test, setTest] = useState<LearnerTest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ submission: TestSubmission | null } | null>(null);

  useEffect(() => {
    let active = true;
    lessonsApi
      .test(lessonId)
      .then((data) => active && setTest(data))
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "Could not load your test."));
    return () => {
      active = false;
    };
  }, [lessonId]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  const view = (first?: TestSubmission | null) => (
    <TestResults lessonId={lessonId} lessonTitle={lessonTitle} questions={test?.questions ?? []} first={first} onOpenLesson={onOpenLesson} />
  );
  if (result && test) return view(result.submission);
  if (!test) return <Skeleton className="h-72 rounded-[22px]" />;
  if (test.submission) return view();
  return <TestRunner lessonId={lessonId} test={test} onChanged={onChanged} onSubmitted={(submission) => setResult({ submission })} />;
}
