"use client";

import { PlusIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { StageBadge } from "@/components/lessons/stage-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { LessonsApi, lessonsApi } from "@/lib/lessons-api";
import type { LessonSummary } from "@/lib/types";

export default function LessonsPage() {
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (search: string, cursor: string | null = null) => {
    try {
      const page = await lessonsApi.list({ q: search, cursor });
      setLessons((current) => (cursor && current ? [...current, ...page.results] : page.results));
      setNext(LessonsApi.cursorOf(page.next));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your lessons.");
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(query), 250); // wait for typing to pause
    return () => clearTimeout(timer);
  }, [query, load]);

  const remove = async (lesson: LessonSummary) => {
    if (!window.confirm(`Delete “${lesson.topic}”? This cannot be undone.`)) return;
    try {
      await lessonsApi.remove(lesson.id);
      setLessons((current) => current?.filter((item) => item.id !== lesson.id) ?? null);
      toast.success("Lesson deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not delete the lesson.");
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-10">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Your lessons</h1>
        <Link href="/lessons/new" className={buttonVariants()}>
          <PlusIcon /> New lesson
        </Link>
      </header>

      <Input
        type="search"
        aria-label="Search lessons"
        placeholder="Search your lessons"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {lessons === null && !error && <div className="h-40" aria-busy="true" />}
      {lessons?.length === 0 && (
        <p className="text-muted-foreground">
          {query ? "No lessons match your search." : "No lessons yet. Start one to see what you already know."}
        </p>
      )}

      <ul className="flex flex-col gap-3">
        {lessons?.map((lesson) => (
          <li key={lesson.id}>
            <Card size="sm">
              <CardContent className="flex items-center justify-between gap-3">
                <Link href={`/lessons/${lesson.id}`} className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="truncate font-medium">{lesson.title || lesson.topic}</span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(lesson.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })}
                  </span>
                </Link>
                <StageBadge stage={lesson.stage} />
                <Button variant="ghost" size="icon" aria-label={`Delete ${lesson.topic}`} onClick={() => remove(lesson)}>
                  <Trash2Icon />
                </Button>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>

      {next && (
        <Button variant="outline" className="self-center" onClick={() => void load(query, next)}>
          Load more
        </Button>
      )}
    </main>
  );
}
