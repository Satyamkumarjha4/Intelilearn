"use client";

import { ArrowRightIcon, BookOpenIcon, PlusIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { LessonCard } from "@/components/lessons/lesson-card";
import { StatusPill } from "@/components/lessons/status-pill";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { ReadPages } from "@/lib/lesson-book";
import { LESSON_FILTERS, LessonStatus } from "@/lib/lesson-status";
import { LessonsApi, lessonsApi } from "@/lib/lessons-api";
import type { LessonSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function LessonsPage() {
  const { user } = useAuth();
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<LessonSummary | null>(null);
  const firstName = user?.name.trim().split(/\s+/)[0] ?? "";

  const load = useCallback(async (search: string, chip: number, cursor: string | null = null) => {
    try {
      const page = await lessonsApi.list({ q: search, stage: LESSON_FILTERS[chip].stages, cursor });
      setLessons((current) => (cursor && current ? [...current, ...page.results] : page.results));
      setNext(LessonsApi.cursorOf(page.next));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't load your lessons.");
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(query, filter), 250); // wait for typing to pause
    return () => clearTimeout(timer);
  }, [query, filter, load]);

  const remove = async (lesson: LessonSummary) => {
    try {
      await lessonsApi.remove(lesson.id);
      setLessons((current) => current?.filter((item) => item.id !== lesson.id) ?? null);
      toast.success("Lesson deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "We couldn't delete the lesson.");
    }
  };

  // Only offered on the plain list: with a search or a filter on, the learner asked for something else. It comes from
  // the lessons loaded so far, which are the newest ones.
  const resume = !query.trim() && filter === 0 && lessons ? LessonStatus.pickContinue(lessons) : null;

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          {firstName && <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">Welcome back, {firstName}</p>}
          <h1 className="font-heading text-3xl font-semibold tracking-tight">My lessons</h1>
        </div>
        <Link href="/lessons/new" className={buttonVariants()}>
          <PlusIcon /> New lesson
        </Link>
      </header>

      {resume && (
        <section aria-labelledby="resume-heading">
          <Card className="border-primary bg-primary-soft">
            <CardContent className="flex flex-wrap items-center justify-between gap-4 px-5">
              <div className="flex min-w-0 flex-col gap-2">
                <h2 id="resume-heading" className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">
                  Continue where you left off
                </h2>
                <p className="font-heading text-xl font-semibold">{resume.title || resume.topic}</p>
                <div>
                  <StatusPill pill={LessonStatus.of(resume, new ReadPages(resume.id).load().size)} />
                </div>
              </div>
              <Link href={`/lessons/${resume.id}`} className={buttonVariants({ size: "lg" })}>
                Continue <ArrowRightIcon />
              </Link>
            </CardContent>
          </Card>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
          {LESSON_FILTERS.map((chip, index) => (
            <button
              key={chip.label}
              type="button"
              aria-pressed={filter === index}
              onClick={() => setFilter(index)}
              className={cn(
                "rounded-full border-2 px-3.5 py-1 text-sm font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                filter === index ? "border-primary bg-primary-soft text-primary-text" : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {chip.label}
            </button>
          ))}
        </div>
        <div className="relative ml-auto w-full sm:w-72">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input type="search" aria-label="Search lessons" placeholder="Search your lessons" className="pl-8" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {lessons === null && !error && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading your lessons">
          {[0, 1, 2].map((n) => (
            <Skeleton key={n} className="h-40 rounded-[22px]" />
          ))}
        </div>
      )}

      {lessons?.length === 0 &&
        (query.trim() || filter !== 0 ? (
          <p className="text-muted-foreground">No lessons match that. Try a different search or filter.</p>
        ) : (
          <Card className="mx-auto w-full max-w-xl">
            <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
              <span className="grid size-14 place-items-center rounded-full bg-primary-soft text-primary-text">
                <BookOpenIcon className="size-7" aria-hidden="true" />
              </span>
              <h2 className="font-heading text-2xl font-semibold">Your first lesson is a quick check away</h2>
              <p className="text-muted-foreground">Tell us what you want to learn. We&apos;ll find out what you already know, then build a lesson just for you.</p>
              <Link href="/lessons/new" className={buttonVariants()}>
                <PlusIcon /> New lesson
              </Link>
            </CardContent>
          </Card>
        ))}

      {lessons && lessons.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {lessons.map((lesson) => (
            <li key={lesson.id}>
              <LessonCard lesson={lesson} onDelete={setDeleting} />
            </li>
          ))}
        </ul>
      )}

      {next && (
        <Button variant="outline" className="self-center" onClick={() => void load(query, filter, next)}>
          Show more lessons
        </Button>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete “${deleting?.title || deleting?.topic || ""}”?`}
        description="The lesson and your answers go away for good. This cannot be undone."
        confirmLabel="Delete lesson"
        cancelLabel="Keep it"
        onConfirm={async () => {
          if (deleting) await remove(deleting);
        }}
      />
    </main>
  );
}
