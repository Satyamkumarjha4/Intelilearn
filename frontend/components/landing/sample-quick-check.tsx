"use client";

import { CheckIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { HERO, REGISTER_HREF } from "@/lib/landing-content";
import { SampleQuiz } from "@/lib/landing/sample-quiz";
import { SAMPLE_CAPTION, SAMPLE_TOPIC } from "@/lib/landing/sample-quiz-content";
import { cn } from "@/lib/utils";

const OPTION_LOOK = {
  open: "border-border bg-card text-foreground hover:bg-muted",
  right: "border-success bg-success-soft text-success-text",
  wrong: "border-destructive bg-destructive-soft text-destructive-text",
  rest: "border-border bg-card text-muted-foreground",
} as const;

/**
 * The sample Quick check in a browser frame: three fixed questions, instant feedback, then the level the score would give and
 * where the lesson would start. All of it is `SampleQuiz`; this only draws it. It makes no network or model call, and it
 * works from the keyboard: after an answer the focus moves to the button that goes on.
 */
export function SampleQuickCheck() {
  const [quiz, setQuiz] = useState(SampleQuiz.start);
  const next = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  useEffect(() => {
    if (quiz.answered) next.current?.focus();
    else if (moved.current) heading.current?.focus();
  }, [quiz]);

  const move = (to: SampleQuiz) => {
    moved.current = true;
    setQuiz(to);
  };

  return (
    <div className="flex min-w-0 flex-[1_1_560px] flex-col gap-3.5">
      <span className="self-center rounded-full bg-primary-soft px-3.5 py-1.5 text-[15px] font-extrabold text-primary-text">{HERO.sampleBadge}</span>
      <div className="overflow-hidden rounded-[20px] border border-border bg-card shadow-[0_24px_56px_oklch(0.26_0.025_190/0.14)] dark:shadow-[0_24px_56px_oklch(0_0_0/0.4)]">
        <div aria-hidden="true" className="flex items-center gap-2 border-b border-border bg-muted px-4 py-3">
          <span className="size-3 rounded-full bg-destructive/60" />
          <span className="size-3 rounded-full bg-marigold/70" />
          <span className="size-3 rounded-full bg-success/60" />
          <span className="ml-3 min-w-0 flex-1 truncate rounded-lg bg-card px-3 py-1 text-[13px] text-muted-foreground">{quiz.done ? "Your lesson" : "Quick check"}</span>
        </div>
        <div className="flex min-h-[440px] flex-col gap-4 px-5 py-7 sm:px-8 sm:py-8">{quiz.done ? <Result quiz={quiz} onRestart={() => move(quiz.restart())} /> : <Question quiz={quiz} heading={heading} next={next} onPick={(i) => move(quiz.pick(i))} onNext={() => move(quiz.next())} />}</div>
      </div>
      <p className="mt-2 text-center text-sm text-muted-foreground">{SAMPLE_CAPTION}</p>
    </div>
  );
}

function Question({ quiz, heading, next, onPick, onNext }: { quiz: SampleQuiz; heading: React.RefObject<HTMLHeadingElement | null>; next: React.RefObject<HTMLButtonElement | null>; onPick: (i: number) => void; onNext: () => void }) {
  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-heading text-2xl font-semibold">Quick check · {SAMPLE_TOPIC}</span>
        <span className="text-[15px] font-extrabold text-muted-foreground">
          {quiz.number} of {quiz.total}
        </span>
      </div>
      <div role="progressbar" aria-label="Quick check progress" aria-valuemin={0} aria-valuemax={quiz.total} aria-valuenow={Math.round(quiz.progress * quiz.total)} className="h-2.5 overflow-hidden rounded-md bg-muted">
        <div className="h-full bg-primary motion-safe:transition-[width]" style={{ width: `${quiz.progress * 100}%` }} />
      </div>
      <h3 ref={heading} tabIndex={-1} className="text-[22px] leading-snug font-extrabold outline-none">
        {quiz.current.question}
      </h3>
      <div role="group" aria-label="Answers" className="flex flex-col gap-3.5">
        {quiz.current.options.map((option, index) => {
          const state = quiz.optionState(index);
          return (
            <button
              key={option}
              type="button"
              onClick={() => onPick(index)}
              aria-disabled={quiz.answered || undefined}
              className={cn("flex items-center justify-between gap-3 rounded-[14px] border-2 px-[18px] py-3.5 text-left text-lg font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50", OPTION_LOOK[state], quiz.answered && "cursor-default")}
            >
              <span>{option}</span>
              {state === "right" ? <CheckIcon aria-label="Right answer" className="size-5 shrink-0" /> : null}
              {state === "wrong" ? <XIcon aria-label="Your answer, not right" className="size-5 shrink-0" /> : null}
            </button>
          );
        })}
      </div>
      <div aria-live="polite" className={cn(quiz.answered && "flex flex-wrap items-center justify-between gap-3.5 rounded-[14px] bg-background px-[18px] py-3.5")}>
        {quiz.answered ? (
          <>
            <span className="min-w-0 flex-[1_1_260px] text-[17px]">{quiz.feedback}</span>
            <Button ref={next} type="button" size="xl" onClick={onNext} className="h-11">
              {quiz.nextLabel}
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Result({ quiz, onRestart }: { quiz: SampleQuiz; onRestart: () => void }) {
  const { level } = quiz;
  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-base font-extrabold text-muted-foreground">
          You got {quiz.score} of {quiz.total}
        </span>
        <span className="rounded-full bg-insight-soft px-3 py-1 text-sm font-extrabold text-insight-text">Your level: {level.name}</span>
      </div>
      <h3 className="font-heading text-[clamp(24px,3vw,30px)] leading-tight font-semibold">Here&apos;s where your lesson would start.</h3>
      <ol aria-label="Your three pages" className="flex flex-wrap gap-2">
        {level.pages.map((page, index) => (
          <li key={page} className={cn("rounded-xl border-2 px-3.5 py-2 text-[15px] font-extrabold", index === 0 ? "border-primary bg-primary-soft text-primary-text" : "border-border bg-background text-foreground")}>
            {index + 1}. {page}
          </li>
        ))}
      </ol>
      <div className="flex flex-col gap-1.5 rounded-2xl border border-dashed border-marigold-deep bg-marigold-soft px-5 py-[18px]">
        <span className="text-sm font-extrabold text-marigold-text">
          Page 1 of {level.pages.length} · {level.pages[0]}
        </span>
        <span className="text-lg">{level.snippet}</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Link href={REGISTER_HREF} className={buttonVariants({ size: "xl" })}>
          Get my real lesson
        </Link>
        <Button type="button" variant="outline" size="xl" onClick={onRestart}>
          Try again
        </Button>
      </div>
    </div>
  );
}
