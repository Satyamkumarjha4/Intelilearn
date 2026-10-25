"use client";

import { CheckIcon, XIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import type { QuizKind, QuizReview as Review } from "@/lib/types";

/** Correct answers and explanations, available only after the attempt. */
export function QuizReview({ lessonId, kind }: { lessonId: string; kind: QuizKind }) {
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const toggle = async () => {
    setOpen((value) => !value);
    if (review || open) return;
    try {
      setReview(await lessonsApi.review(lessonId, kind));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the review.");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <Button variant="outline" className="self-start" onClick={toggle} aria-expanded={open}>
        {open ? "Hide review" : "Review answers"}
      </Button>
      {open && error && <p className="text-sm text-destructive">{error}</p>}
      {open && review && (
        <ol className="flex flex-col gap-4">
          {review.questions.map((q, n) => (
            <li key={q.id} className="flex flex-col gap-1 rounded-lg border p-3 text-sm">
              <p className="flex items-start gap-2 font-medium">
                {q.correct ? (
                  <CheckIcon className="mt-0.5 size-4 shrink-0 text-success" aria-label="correct" />
                ) : (
                  <XIcon className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="wrong" />
                )}
                <span>
                  {n + 1}. {q.question}
                </span>
              </p>
              <p>
                <span className="text-muted-foreground">Your answer: </span>
                {q.answer === "dont_know" ? "I don't know" : q.options[q.answer]}
              </p>
              {!q.correct && (
                <p>
                  <span className="text-muted-foreground">Correct answer: </span>
                  {q.options[q.correct_index]}
                </p>
              )}
              <p className="text-muted-foreground">{q.explanation}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
