"use client";

import { useEffect, useMemo, useReducer, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { DONT_KNOW, QuizSession } from "@/lib/quiz-session";
import type { QuizForLearner, QuizKind, QuizResultSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  lessonId: string;
  kind: QuizKind;
  onSubmitted: (result: QuizResultSummary, runId: string) => void;
};

const INTRO: Record<QuizKind, { title: string; text: string }> = {
  diagnostic: {
    title: "A quick check of what you know",
    text: "Guessing makes your lesson worse, because it assumes you know things you don't. If you're unsure, “I don't know” is the useful answer.",
  },
  prerequisite: {
    title: "Let's check the foundations first",
    text: "A few basics this topic builds on. Again, “I don't know” is a fine answer.",
  },
};

/** One question per screen. Every question needs an answer; “I don't know” counts as one. */
export function QuizRunner({ lessonId, kind, onSubmitted }: Props) {
  const [quiz, setQuiz] = useState<QuizForLearner | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    lessonsApi
      .quiz(lessonId, kind)
      .then((data) => active && setQuiz(data))
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "Could not load the quiz."));
    return () => {
      active = false;
    };
  }, [lessonId, kind]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!quiz) return <div className="h-64" aria-busy="true" />;
  return <Session quiz={quiz} lessonId={lessonId} kind={kind} onSubmitted={onSubmitted} />;
}

function Session({ quiz, lessonId, kind, onSubmitted }: Props & { quiz: QuizForLearner }) {
  const session = useMemo(() => new QuizSession(quiz.questions), [quiz]);
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const [submitting, setSubmitting] = useState(false);
  const question = session.current!;
  const chosen = session.answerOf(question.id);

  const choose = (value: number | typeof DONT_KNOW) => {
    session.answer(value);
    rerender();
  };
  const move = (step: () => void) => {
    step();
    rerender();
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      const { result, run_id } = await lessonsApi.submitQuiz(lessonId, kind, session.payload());
      onSubmitted(result, run_id);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not submit your answers.");
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">
          <h1>{INTRO[kind].title}</h1>
        </CardTitle>
        <CardDescription>{INTRO[kind].text}</CardDescription>
        <Progress value={session.progress} label="Questions answered" className="mt-2" />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          Question {session.index + 1} of {quiz.questions.length}
        </p>
        <p className="text-lg font-medium whitespace-pre-wrap">{question.question}</p>
        <div role="radiogroup" aria-label="Answers" className="flex flex-col gap-2">
          {question.options.map((option, index) => (
            <Choice key={index} selected={chosen === index} onClick={() => choose(index)}>
              {option}
            </Choice>
          ))}
          {quiz.allow_dont_know && (
            <Choice selected={chosen === DONT_KNOW} muted onClick={() => choose(DONT_KNOW)}>
              I don&apos;t know
            </Choice>
          )}
        </div>
      </CardContent>
      <CardFooter className="justify-between">
        <Button variant="outline" disabled={session.index === 0} onClick={() => move(() => session.back())}>
          Back
        </Button>
        {session.isLast ? (
          <Button disabled={!session.isComplete || submitting} onClick={submit}>
            {submitting ? "Submitting…" : "Submit answers"}
          </Button>
        ) : (
          <Button disabled={chosen === undefined} onClick={() => move(() => session.next())}>
            Next
          </Button>
        )}
      </CardFooter>
      {session.isLast && !session.isComplete && (
        <p className="px-4 pb-3 text-sm text-muted-foreground">
          Question {(session.firstUnanswered() ?? 0) + 1} still needs an answer.
        </p>
      )}
    </Card>
  );
}

function Choice({
  selected,
  muted,
  onClick,
  children,
}: {
  selected: boolean;
  muted?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={cn(
        "rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
        selected && "border-primary bg-primary/5 ring-1 ring-primary",
        muted && !selected && "text-muted-foreground",
      )}
    >
      {children}
    </button>
  );
}
