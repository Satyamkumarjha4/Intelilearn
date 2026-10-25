"use client";

import { useCallback, useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { topicSuggestions, TopicPick, type SuggestionAnswers, type SuggestionPage, type TopicSuggestion } from "@/lib/topic-suggestions";
import { cn } from "@/lib/utils";

type Props = {
  /** What the suggestions are based on, as chips. */
  summary: string[];
  /** The answers the topics are picked from. */
  answers: SuggestionAnswers;
  pick: TopicPick;
  onPick: (pick: TopicPick) => void;
  /** Back to step 1. */
  onChange: () => void;
  error: string | null;
};

type Load = { state: "loading" } | { state: "failed" } | { state: "ready"; page: SuggestionPage; number: number };

/** Step 5: topics picked for the learner (four at a time), or a topic of their own. */
export function TopicStep({ summary, answers, pick, onPick, onChange, error }: Props) {
  const [load, setLoad] = useState<Load>({ state: "loading" });

  const fetchPage = useCallback(
    (number: number) => {
      setLoad({ state: "loading" });
      topicSuggestions
        .page(answers, number)
        .then((page) => setLoad(page.topics.length ? { state: "ready", page, number } : { state: "failed" }))
        .catch(() => setLoad({ state: "failed" }));
    },
    [answers],
  );

  useEffect(() => {
    let active = true;
    topicSuggestions
      .page(answers, 0)
      .then((page) => active && setLoad(page.topics.length ? { state: "ready", page, number: 0 } : { state: "failed" }))
      .catch(() => active && setLoad({ state: "failed" }));
    return () => {
      active = false;
    };
    // The first page is fetched once, when the step opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 tabIndex={-1} className="font-heading text-3xl font-semibold tracking-tight outline-none">
          Where would you like to start?
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">Based on</span>
          {summary.map((chip) => (
            <Badge key={chip} variant="primary">
              {chip}
            </Badge>
          ))}
          <button type="button" onClick={onChange} className="rounded-md text-sm font-extrabold text-primary-text underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            Change
          </button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {load.state === "loading" && (
        <div className="flex flex-col gap-3" aria-busy="true">
          <p role="status" className="flex items-center gap-2 text-sm font-semibold text-insight-text">
            <span aria-hidden="true" className="size-2.5 rounded-full bg-insight motion-safe:animate-pulse" />
            Finding good first topics for you…
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {[0, 1, 2, 3].map((n) => (
              <Skeleton key={n} className="h-28 rounded-2xl" />
            ))}
          </div>
        </div>
      )}

      {load.state === "failed" && <p className="rounded-xl bg-muted px-4 py-3 text-muted-foreground">We couldn&apos;t find topic ideas just now. No problem: type a topic of your own below.</p>}

      {load.state === "ready" && (
        <section aria-labelledby="picked-heading" className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <h2 id="picked-heading" className="text-sm font-extrabold text-insight-text">
              Picked for you
            </h2>
            {load.page.hasMore && (
              <Button variant="ghost" size="sm" onClick={() => fetchPage(load.number + 1)}>
                Show me others
              </Button>
            )}
          </div>
          <div role="radiogroup" aria-label="Topics picked for you" className="grid gap-3 sm:grid-cols-2">
            {load.page.topics.map((card) => (
              <SuggestionCard key={card.title} card={card} chosen={pick.selected?.title === card.title} onPick={() => onPick(pick.pick(card))} />
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-col gap-2">
        <label htmlFor="own-topic" className="text-sm font-extrabold text-muted-foreground">
          Or type your own topic
        </label>
        <Input id="own-topic" value={pick.typed} maxLength={200} autoComplete="off" placeholder="Binary search, photosynthesis…" onChange={(e) => onPick(pick.type(e.target.value))} className="h-11 text-base" />
      </div>
    </div>
  );
}

function SuggestionCard({ card, chosen, onPick }: { card: TopicSuggestion; chosen: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={chosen}
      onClick={onPick}
      className={cn(
        "flex flex-col items-start gap-1.5 rounded-2xl border-2 p-4 text-left outline-none motion-safe:transition-[transform,box-shadow,background-color] focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-0.5",
        chosen ? "border-primary bg-primary-soft shadow-[0_3px_0_var(--primary)]" : "border-border bg-card shadow-[0_3px_0_var(--border)] hover:bg-muted",
      )}
    >
      {card.subject && <span className="rounded-full bg-insight-soft px-2 py-0.5 text-xs font-extrabold text-insight-text">{card.subject}</span>}
      <span className="font-heading text-lg leading-snug font-semibold">{card.title}</span>
      {card.reason && <span className="text-sm text-muted-foreground">{card.reason}</span>}
    </button>
  );
}
