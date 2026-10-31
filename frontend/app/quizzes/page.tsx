"use client";

import { ListChecksIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { QuizCard } from "@/components/quizzes/quiz-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { LessonsApi } from "@/lib/lessons-api";
import { quizzesApi } from "@/lib/quizzes-api";
import type { QuizSummary } from "@/lib/types";

export default function QuizzesPage() {
  const [quizzes, setQuizzes] = useState<QuizSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<QuizSummary | null>(null);

  const load = useCallback(async (cursor: string | null = null) => {
    try {
      const page = await quizzesApi.list(cursor);
      setQuizzes((current) => (cursor && current ? [...current, ...page.results] : page.results));
      setNext(LessonsApi.cursorOf(page.next));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't load your quizzes.");
    }
  }, []);

  useEffect(() => {
    let active = true;
    quizzesApi
      .list()
      .then((page) => {
        if (!active) return;
        setQuizzes(page.results);
        setNext(LessonsApi.cursorOf(page.next));
      })
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "We couldn't load your quizzes."));
    return () => {
      active = false;
    };
  }, []);

  const remove = async (quiz: QuizSummary) => {
    try {
      await quizzesApi.remove(quiz.id);
      setQuizzes((current) => current?.filter((item) => item.id !== quiz.id) ?? null);
      toast.success("Quiz deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "We couldn't delete the quiz.");
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">Practice</p>
          <h1 className="font-heading text-3xl font-semibold tracking-tight">Quick quizzes</h1>
        </div>
        <Link href="/quizzes/new" className={buttonVariants()}>
          <PlusIcon /> New quiz
        </Link>
      </header>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {quizzes === null && !error && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading your quizzes">
          {[0, 1, 2].map((n) => (
            <Skeleton key={n} className="h-36 rounded-[22px]" />
          ))}
        </div>
      )}

      {quizzes?.length === 0 && (
        <Card className="mx-auto w-full max-w-xl">
          <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
            <span className="grid size-14 place-items-center rounded-full bg-primary-soft text-primary-text">
              <ListChecksIcon className="size-7" aria-hidden="true" />
            </span>
            <h2 className="font-heading text-2xl font-semibold">Test yourself, any time</h2>
            <p className="text-muted-foreground">A quick quiz is a handful of questions on a topic, or on the lessons you&apos;ve made. Take it as often as you like: every try has new questions.</p>
            <Link href="/quizzes/new" className={buttonVariants()}>
              <PlusIcon /> New quiz
            </Link>
          </CardContent>
        </Card>
      )}

      {quizzes && quizzes.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {quizzes.map((quiz) => (
            <li key={quiz.id}>
              <QuizCard quiz={quiz} onDelete={setDeleting} />
            </li>
          ))}
        </ul>
      )}

      {next && (
        <Button variant="outline" className="self-center" onClick={() => void load(next)}>
          Show more quizzes
        </Button>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete “${deleting?.topic ?? ""}”?`}
        description="The quiz and your tries go away for good. This cannot be undone."
        confirmLabel="Delete quiz"
        cancelLabel="Keep it"
        onConfirm={async () => {
          if (deleting) await remove(deleting);
        }}
      />
    </main>
  );
}
