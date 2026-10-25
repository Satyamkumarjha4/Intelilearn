"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Difficulty } from "@/components/landing/difficulty";
import { DemoOption } from "@/components/landing/demo-option";
import { LevelReadout } from "@/components/landing/level-readout";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DeckMotion } from "@/lib/deck-motion";
import { DemoQuestionFetcher, DemoQuestions } from "@/lib/demo-question";
import { DONT_KNOW_ANSWER, HeroDemo, type HeroAnswer } from "@/lib/hero-demo";
import { REGISTER_HREF } from "@/lib/landing-content";
import type { DemoQuestion } from "@/lib/types";
import { cn } from "@/lib/utils";

type View = "question" | "result";

const CARD = "gap-0 [--card-spacing:--spacing(6)] focus-visible:outline-none";
const GHOST = "rounded-[22px] border-[1.5px] border-border bg-card";

/**
 * The try-it card: one real question, picked at random on the server for this page load. Choosing an answer marks it,
 * the card flies off like the quick check's cards do and "Your starting point" rises from the stack; "Try again" flies
 * to another question. While the result is on screen the next question is already being fetched, so Try again does not
 * wait. Nothing the visitor answers is sent anywhere.
 */
export function HeroDemoCard({ initial }: { initial: DemoQuestion }) {
  const [view, setView] = useState<View>("question");
  const [leaving, setLeaving] = useState<View | null>(null);
  const [question, setQuestion] = useState(initial);
  // `picked` marks the question; `answered` and `given` are what the result talks about, kept while the result flies
  // off again (by then `question` is already the next one).
  const [picked, setPicked] = useState<HeroAnswer | null>(null);
  const [answered, setAnswered] = useState(initial);
  const [given, setGiven] = useState<HeroAnswer>(DONT_KNOW_ANSWER);
  const upcoming = useRef<Promise<DemoQuestion | null> | null>(null);
  const changing = useRef(false);
  const flying = useRef<HTMLDivElement>(null);
  const rising = useRef<HTMLDivElement>(null);
  const timers = useRef<number[]>([]);
  const moved = useRef(false);

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    if (!leaving) return;
    DeckMotion.fly(flying.current);
    DeckMotion.rise(rising.current);
  }, [leaving]);

  // A visitor who answered, or went back, has lost the button they pressed: put them on the card that arrived.
  useEffect(() => {
    if (moved.current) rising.current?.focus({ preventScroll: true });
  }, [view]);

  const show = (next: View) => {
    moved.current = true;
    const lessMotion = DeckMotion.prefersLessMotion();
    setLeaving(lessMotion ? null : view);
    setView(next);
    if (next === "question") setPicked(null);
    if (!lessMotion) timers.current.push(window.setTimeout(() => setLeaving(null), DeckMotion.FLY_MS));
  };

  const answer = (value: HeroAnswer) => {
    if (picked !== null) return;
    setPicked(value);
    setGiven(value);
    setAnswered(question);
    upcoming.current = new DemoQuestionFetcher().fetch({ exclude: question.id });
    timers.current.push(window.setTimeout(() => show("result"), DeckMotion.FLY_MS));
  };

  const tryAgain = async () => {
    if (changing.current) return;
    changing.current = true;
    const next = (await (upcoming.current ?? new DemoQuestionFetcher().fetch({ exclude: answered.id }))) ?? DemoQuestions.afterFailure(answered.id);
    upcoming.current = null;
    setQuestion(next ?? answered);
    show("question");
    changing.current = false;
  };

  const card = (which: View, ref?: React.Ref<HTMLDivElement>, className?: string) => (
    <Card ref={ref} tabIndex={-1} className={cn(CARD, className)}>
      <CardContent>{which === "question" ? questionView : resultView}</CardContent>
    </Card>
  );

  const questionView = (
    <div className="flex flex-col">
      <Difficulty filled={question.band} total={5} label={DemoQuestions.label(question)} />
      <p className="mt-3 font-heading text-[21px] leading-tight font-semibold text-balance">{question.question}</p>
      <div role="group" aria-label="Answers" className="mt-[18px] grid gap-2.5">
        {question.options.map((option, index) => (
          <DemoOption key={option} k={index + 1} state={picked === index ? (HeroDemo.isRight(question, index) ? "right" : "picked") : "idle"} onClick={() => answer(index)}>
            {option}
          </DemoOption>
        ))}
      </div>
      <button
        type="button"
        aria-pressed={picked === DONT_KNOW_ANSWER}
        onClick={() => answer(DONT_KNOW_ANSWER)}
        className={cn(
          "mt-2.5 rounded-2xl border-2 border-dashed p-2.5 text-center text-sm font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          picked === DONT_KNOW_ANSWER ? "border-marigold bg-marigold-soft text-marigold-text" : "border-border text-muted-foreground hover:bg-muted",
        )}
      >
        I don&apos;t know this yet
      </button>
    </div>
  );

  const copy = HeroDemo.resultFor(answered, given);
  const resultView = (
    <div className="flex flex-col">
      <p className="font-mono text-[11px] font-medium tracking-widest text-insight-text uppercase">{copy.eyebrow}</p>
      <p className="mt-1 font-heading text-[22px] font-semibold">Your starting point</p>
      <div className="mt-5">
        <LevelReadout filled={copy.level} label={copy.levelLabel} />
      </div>
      <div className="mt-4 rounded-2xl border-2 border-dashed border-insight bg-insight-soft p-4">
        <p className="mb-1 font-mono text-[11px] font-medium tracking-widest text-insight-text uppercase">Your lesson would begin with</p>
        <p className="font-bold">{copy.startsWith}</p>
      </div>
      <div className="mt-[18px] flex flex-wrap items-center gap-2.5">
        <Link href={REGISTER_HREF} className={buttonVariants({ size: "lg" })}>
          Try it on your own topic
        </Link>
        <Button variant="link" className="text-muted-foreground" onClick={tryAgain}>
          Try again
        </Button>
      </div>
    </div>
  );

  return (
    <div>
      <div className="flex items-center gap-2.5 text-[13px] font-extrabold text-primary-text">
        <span aria-hidden="true" className="size-2.5 rounded-full bg-primary motion-safe:animate-[ask-pulse_1.8s_infinite]" />
        Socra asks first. Try one:
      </div>
      <div aria-live="polite" className="isolate mt-3.5 grid pb-7 *:col-start-1 *:row-start-1">
        <div aria-hidden="true" className={cn(GHOST, "z-0 translate-y-[26px] scale-[0.93] motion-safe:transition-opacity", view === "result" ? "opacity-0" : "opacity-70")} />
        <div aria-hidden="true" className={cn(GHOST, "z-[1] translate-y-[13px] scale-[0.965]")} />
        {card(view, rising, "relative z-[2]")}
        {leaving && (
          <div ref={flying} aria-hidden="true" inert className="pointer-events-none z-[3] flex flex-col *:flex-1">
            {card(leaving)}
          </div>
        )}
      </div>
    </div>
  );
}
