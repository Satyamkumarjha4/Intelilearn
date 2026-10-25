"use client";

import { LockIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { SegmentBar } from "@/components/lessons/segment-bar";
import { Button } from "@/components/ui/button";
import { DeckMotion } from "@/lib/deck-motion";
import type { DeckSession } from "@/lib/deck-session";

type Props = {
  session: DeckSession;
  /** A card's content. `locked` is true for a card the learner has continued past (the one flying off). */
  renderCard: (id: string, locked: boolean) => React.ReactNode;
  /** Called when the learner presses Continue (or Enter) on a card that has an answer. */
  onContinue: () => void;
  /** The key handler for answers (1–4, A–D…): called with a lower-case key unless someone is typing. */
  onKey?: (key: string, id: string) => void;
  lockHint: string;
  continueLabel: string;
  finishLabel: string;
  /** The look of the last card's button. */
  finishVariant?: "default" | "marigold";
  /** Disables Continue while the answers are being sent. */
  busy?: boolean;
  label: string;
};

/**
 * One card at a time, forward only. Two ghost cards sit behind it and thin out as fewer remain; the answered card flies
 * off to the left and the next rises from the stack (instantly, for a learner who asked for less motion). A segmented
 * bar and "n / total" show the place. The state is the `DeckSession`; this only draws it and listens for keys.
 */
export function FlashcardDeck({ session, renderCard, onContinue, onKey, lockHint, continueLabel, finishLabel, finishVariant = "default", busy, label }: Props) {
  const id = session.current;
  const flying = useRef<HTMLDivElement>(null);
  const rising = useRef<HTMLDivElement>(null);
  // The card that has just been continued past, kept on screen while it flies off ("adjusting state during render").
  const [seen, setSeen] = useState({ index: session.index, finished: session.finished });
  const [leaving, setLeaving] = useState<{ id: string; key: number } | null>(null);
  if (seen.index !== session.index || seen.finished !== session.finished) {
    const left = seen.finished ? undefined : session.ids[seen.index];
    setSeen({ index: session.index, finished: session.finished });
    setLeaving(left !== undefined && (session.index > seen.index || session.finished) && !DeckMotion.prefersLessMotion() ? { id: left, key: seen.index } : null);
  }

  useEffect(() => {
    if (!leaving) return;
    DeckMotion.fly(flying.current);
    DeckMotion.rise(rising.current);
    const timer = setTimeout(() => setLeaving(null), DeckMotion.FLY_MS);
    return () => clearTimeout(timer);
  }, [leaving]);

  const latest = useRef({ session, onContinue, onKey, busy });
  useEffect(() => {
    latest.current = { session, onContinue, onKey, busy };
  });

  useEffect(() => {
    const listen = (event: KeyboardEvent) => {
      const { session: deck, onContinue: next, onKey: pick, busy: waiting } = latest.current;
      const target = event.target as HTMLElement | null;
      if (event.altKey || event.ctrlKey || event.metaKey || target?.closest?.('[role="dialog"], [role="menu"]') || waiting) return;
      const typing = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement || target instanceof HTMLSelectElement;
      if (event.key === "Enter") {
        if (target instanceof HTMLTextAreaElement || target?.closest?.("[data-deck-continue]")) return; // a textarea wants its newline; the button clicks itself
        if (deck.canContinue) {
          event.preventDefault();
          next();
        }
        return;
      }
      if (!typing && deck.current !== undefined && !event.shiftKey) pick?.(event.key.toLowerCase(), deck.current);
    };
    window.addEventListener("keydown", listen);
    return () => window.removeEventListener("keydown", listen);
  }, []);

  const ghosts = Math.min(2, session.total - session.index - 1);
  const lastLabel = session.isLast ? finishLabel : continueLabel;

  return (
    <div className="flex flex-col gap-4" role="group" aria-label={label}>
      <div className="flex items-center gap-3">
        <SegmentBar segments={session.segments} now={Math.min(session.index + 1, session.total)} />
        <span className="font-mono text-sm text-muted-foreground tabular-nums">
          {Math.min(session.index + 1, session.total)} / {session.total}
        </span>
      </div>

      <div className="relative pb-5">
        {Array.from({ length: ghosts }, (_, n) => (
          <div
            key={n}
            aria-hidden="true"
            className="absolute inset-x-0 top-0 bottom-5 rounded-[22px] border-[1.5px] border-border bg-card motion-safe:transition-transform"
            style={{ transform: `translateY(${(n + 1) * 10}px) scale(${1 - (n + 1) * 0.04})`, zIndex: -n - 1 }}
          />
        ))}
        {id !== undefined && (
          <div ref={rising} key={id} className="relative rounded-[22px] border-[1.5px] border-border bg-card p-5 shadow-card sm:p-6">
            {renderCard(id, false)}
          </div>
        )}
        {leaving && (
          <div
            ref={flying}
            key={leaving.key}
            aria-hidden="true"
            inert
            className="pointer-events-none absolute inset-x-0 top-0 z-10 rounded-[22px] border-[1.5px] border-border bg-card p-5 shadow-card sm:p-6"
          >
            {renderCard(leaving.id, true)}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <LockIcon className="size-4" aria-hidden="true" /> {lockHint}
        </p>
        <Button data-deck-continue variant={session.isLast ? finishVariant : "default"} disabled={!session.canContinue || busy || id === undefined} onClick={onContinue}>
          {lastLabel}
        </Button>
      </div>
    </div>
  );
}
