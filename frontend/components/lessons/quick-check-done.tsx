"use client";

import { CheckCircle2Icon, Loader2Icon } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { QuizNames } from "@/lib/quiz-names";
import type { QuizKind } from "@/lib/types";

type Props = {
  kind: QuizKind;
  /** `sending` while the answers go to the server, `failed` when they did not get there, `sent` once the lesson is working on them. */
  state: "sending" | "failed" | "sent";
  error?: string;
  onRetry?: () => void;
};

const NEXT: Record<QuizKind, string> = {
  diagnostic: "Working out your starting point…",
  prerequisite: "Putting your lesson together…",
};

/** The card that flips in when the last question is done. */
export function QuickCheckDone({ kind, state, error, onRetry }: Props) {
  const card = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    card.current?.animate?.([{ transform: "perspective(800px) rotateY(90deg)", opacity: 0 }, { transform: "perspective(800px) rotateY(0)", opacity: 1 }], {
      duration: 450,
      easing: "ease-out",
    });
  }, []);
  return (
    <div ref={card}>
      <Card>
        <CardContent className="flex flex-col items-center gap-3 px-6 py-6 text-center">
          <CheckCircle2Icon className="size-12 text-success" aria-hidden="true" />
          <h1 className="font-heading text-2xl font-semibold tracking-tight">{QuizNames.done(kind)}</h1>
          {state === "failed" ? (
            <>
              <p role="alert" className="text-muted-foreground">
                {error || "We couldn't send your answers."} They&apos;re saved on this page, so nothing is lost.
              </p>
              <Button onClick={onRetry}>Send my answers</Button>
            </>
          ) : (
            <p className="flex items-center gap-2 text-muted-foreground" aria-live="polite">
              <Loader2Icon className="size-4 text-primary motion-safe:animate-spin" aria-hidden="true" />
              {state === "sending" ? "Sending your answers…" : NEXT[kind]}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
