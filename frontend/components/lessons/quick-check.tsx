"use client";

import { useEffect, useState } from "react";

import { FlashcardDeck } from "@/components/lessons/flashcard-deck";
import { QuickCheckDone } from "@/components/lessons/quick-check-done";
import { useDeck } from "@/components/lessons/use-deck";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ApiError } from "@/lib/api";
import { DONT_KNOW } from "@/lib/deck-session";
import { lessonsApi } from "@/lib/lessons-api";
import { BAND_LABELS, BAND_ORDER } from "@/lib/stage-view";
import type { LearnerQuestion, QuizForLearner, QuizKind, QuizResultSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  lessonId: string;
  kind: QuizKind;
  onSubmitted: (result: QuizResultSummary, runId: string) => void;
  /** The server says this quiz was already answered: the page should show the answers instead. */
  onAlreadyAttempted: () => void;
};

const TITLE: Record<QuizKind, string> = {
  diagnostic: "Quick check",
  prerequisite: "Quick check · the basics first",
};
const REASSURANCE: Record<QuizKind, string> = {
  diagnostic: "There are no marks here. Guessing makes your lesson worse, because it assumes you know things you don't, so “I don't know” is a great answer.",
  prerequisite: "A few basics this topic builds on. “I don't know” is a fine answer here too.",
};

/** The quick check (and the foundations check): one card per question, forward only, all answers sent at the end. */
export function QuickCheck(props: Props) {
  const [quiz, setQuiz] = useState<QuizForLearner | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    lessonsApi
      .quiz(props.lessonId, props.kind)
      .then((data) => active && setQuiz(data))
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.code === "already_attempted") props.onAlreadyAttempted();
        else setError(err instanceof ApiError ? err.message : "Could not load your quick check.");
      });
    return () => {
      active = false;
    };
    // `onAlreadyAttempted` is read once, when the quiz fails to load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.lessonId, props.kind]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!quiz) return <div className="h-64" aria-busy="true" />;
  return <Cards quiz={quiz} {...props} />;
}

function Cards({ quiz, lessonId, kind, onSubmitted, onAlreadyAttempted }: Props & { quiz: QuizForLearner }) {
  const ids = quiz.questions.map((q) => q.id);
  const { deck, answer, advance, clear } = useDeck(`${lessonId}:${kind}`, ids);
  // A refresh after the last card leaves a finished deck whose answers never got sent: offer to send them.
  const [phase, setPhase] = useState<"idle" | "sending" | "failed">(deck.finished ? "failed" : "idle");
  const [failure, setFailure] = useState("");
  const byId = new Map(quiz.questions.map((q) => [q.id, q]));

  const send = async () => {
    setPhase("sending");
    try {
      const { result, run_id } = await lessonsApi.submitQuiz(lessonId, kind, deck.payload() as Record<string, number | typeof DONT_KNOW>);
      clear();
      onSubmitted(result, run_id);
    } catch (err) {
      if (err instanceof ApiError && err.code === "already_attempted") {
        clear();
        onAlreadyAttempted();
        return;
      }
      setFailure(err instanceof ApiError ? err.message : "");
      setPhase("failed");
    }
  };

  const onContinue = () => {
    const last = deck.isLast;
    advance();
    if (last) void send();
  };

  if (deck.finished) return <QuickCheckDone kind={kind} state={phase === "failed" ? "failed" : "sending"} error={failure} onRetry={send} />;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-mono text-xs font-bold tracking-wider text-insight-text uppercase">{TITLE[kind]}</h1>
      <FlashcardDeck
        label="Quick check questions"
        session={deck}
        lockHint="No going back once you continue"
        continueLabel="Continue"
        finishLabel="Finish"
        onContinue={onContinue}
        onKey={(key, id) => {
          const question = byId.get(id);
          const option = Number(key) - 1;
          if (question && Number.isInteger(option) && option >= 0 && option < question.options.length) answer(option);
          else if (key === "d" && quiz.allow_dont_know) answer(DONT_KNOW);
        }}
        renderCard={(id, locked) => {
          const question = byId.get(id)!;
          return <Card question={question} answer={deck.answerOf(id)} locked={locked} onAnswer={answer} allowDontKnow={quiz.allow_dont_know} />;
        }}
      />
      <p className="text-center text-sm text-muted-foreground">{REASSURANCE[kind]}</p>
    </div>
  );
}

function Card({ question, answer, locked, onAnswer, allowDontKnow }: {
  question: LearnerQuestion;
  answer: number | string | undefined;
  locked: boolean;
  onAnswer: (value: number | typeof DONT_KNOW) => void;
  allowDontKnow: boolean;
}) {
  const level = question.band ? BAND_ORDER.indexOf(question.band) + 1 : 0;
  return (
    <div className="flex flex-col gap-4">
      {level > 0 && question.band && (
        <div className="flex items-center gap-2 text-xs font-bold text-insight-text">
          <span role="img" aria-label={`Difficulty ${level} of ${BAND_ORDER.length}`} className="flex gap-1">
            {BAND_ORDER.map((band, n) => (
              <span key={band} className={cn("h-2 w-5 rounded-full", n < level ? "bg-insight" : "bg-insight-soft")} />
            ))}
          </span>
          {BAND_LABELS[question.band]}
        </div>
      )}
      <p className="font-heading text-xl leading-snug font-medium whitespace-pre-wrap">{question.question}</p>
      <div role="radiogroup" aria-label="Answers" className="flex flex-col gap-2">
        {question.options.map((option, index) => (
          <button
            key={index}
            type="button"
            role="radio"
            data-deck-option
            aria-checked={answer === index}
            disabled={locked}
            onClick={() => onAnswer(index)}
            className={cn(
              "flex items-center gap-3 rounded-xl border-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
              answer === index ? "border-primary bg-primary-soft" : "border-border",
            )}
          >
            <span className={cn("grid size-6 shrink-0 place-items-center rounded-md font-mono text-xs font-bold", answer === index ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
              {index + 1}
            </span>
            {option}
          </button>
        ))}
      </div>
      {allowDontKnow && (
        <button
          type="button"
          role="radio"
          data-deck-option
          aria-checked={answer === DONT_KNOW}
          disabled={locked}
          onClick={() => onAnswer(DONT_KNOW)}
          className={cn(
            "rounded-xl border-2 border-dashed px-3 py-2.5 text-center text-sm font-semibold transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
            answer === DONT_KNOW ? "border-marigold bg-marigold-soft text-marigold-text" : "border-border text-muted-foreground",
          )}
        >
          I don&apos;t know this yet (D)
        </button>
      )}
    </div>
  );
}
