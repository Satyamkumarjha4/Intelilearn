"use client";

import { useEffect, useRef, useState } from "react";

import { Reveal } from "@/components/landing/reveal";
import { usePrefersReducedMotion } from "@/components/landing/use-reduced-motion";
import { BookPreview, CheckPreview, ResultPreview, StartingPointPreview } from "@/components/landing/walkthrough-previews";
import { WALK_STEPS } from "@/lib/landing-content";
import { Walkthrough } from "@/lib/walkthrough";
import { cn } from "@/lib/utils";

const PREVIEWS = [CheckPreview, StartingPointPreview, BookPreview, ResultPreview];

type StepProps = { index: number; selected: boolean; playing: boolean; onChoose: () => void; buttonRef: (node: HTMLButtonElement | null) => void };

function Step({ index, selected, playing, onChoose, buttonRef }: StepProps) {
  const { title, text } = WALK_STEPS[index];
  return (
    <button
      type="button"
      role="tab"
      id={`walk-tab-${index}`}
      aria-selected={selected}
      aria-controls="walk-panel"
      tabIndex={selected ? 0 : -1}
      onClick={onChoose}
      ref={buttonRef}
      className={cn(
        "relative grid w-full grid-cols-[36px_minmax(0,1fr)] gap-x-3.5 gap-y-0.5 overflow-hidden rounded-[18px] border-2 px-[18px] py-4 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        "motion-safe:transition-[border-color,background-color]",
        selected ? "border-primary bg-primary-soft shadow-[0_4px_0_var(--primary)]" : "border-border bg-card hover:border-primary",
      )}
    >
      <span aria-hidden="true" className={cn("row-span-2 grid size-9 place-items-center rounded-[11px] font-extrabold", selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
        {index + 1}
      </span>
      <span className="text-[16.5px] font-extrabold">{title}</span>
      <span className="block text-sm text-muted-foreground">{text}</span>
      <span aria-hidden="true" className={cn("absolute bottom-0 left-0 h-1 w-0 bg-primary", selected && playing && "animate-[tick_5s_linear_forwards]")} />
    </button>
  );
}

/**
 * "How it works": four steps on the left, a preview of the real screen on the right. Once it has scrolled into view the
 * steps play on their own, one every five seconds, with a bar along the bottom of the active step; choosing a step (by
 * click or arrow key) stops that. A visitor who asked for less motion gets no autoplay.
 */
export function WalkthroughSection() {
  const [walk, setWalk] = useState(() => Walkthrough.start(WALK_STEPS.length));
  const [seen, setSeen] = useState(false);
  const lessMotion = usePrefersReducedMotion();
  const playing = walk.autoplay && !lessMotion && seen;
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(() => setWalk((current) => current.advance()), Walkthrough.STEP_MS);
    return () => window.clearTimeout(timer);
  }, [playing, walk.index]);

  const choose = (next: Walkthrough, focus = false) => {
    setWalk(next);
    if (focus) tabs.current[next.index]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const direction = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key] as 1 | -1 | undefined;
    if (!direction) return;
    event.preventDefault();
    choose(walk.step(direction), true);
  };

  const Preview = PREVIEWS[walk.index];
  return (
    <div className="mt-6 grid grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] items-stretch gap-8 max-[900px]:grid-cols-1">
      <div role="tablist" aria-label="How it works" aria-orientation="vertical" onKeyDown={onKeyDown} className="grid content-start gap-2.5">
        {WALK_STEPS.map((step, index) => (
          <Reveal key={step.title} index={index} role="presentation">
            <Step
              index={index}
              selected={index === walk.index}
              playing={playing}
              onChoose={() => choose(walk.choose(index))}
              buttonRef={(node) => {
                tabs.current[index] = node;
              }}
            />
          </Reveal>
        ))}
      </div>
      {/* The stage is as tall as the step list beside it (the grid stretches it), and what it shows sits at the top: the
          caption chip at the left, the preview right under it. */}
      <Reveal onShow={() => setSeen(true)} className="relative flex flex-col items-center justify-start gap-4 rounded-[26px] border-[1.5px] border-border bg-muted px-6 pt-5 pb-6 max-[900px]:p-[18px]">
        <span className="inline-flex max-w-full items-center gap-2 self-start rounded-full border-[1.5px] border-border bg-card px-3 py-1 text-[12.5px] font-extrabold text-muted-foreground">
          <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-primary" />
          {WALK_STEPS[walk.index].caption}
        </span>
        <div key={walk.index} role="tabpanel" id="walk-panel" aria-labelledby={`walk-tab-${walk.index}`} data-play={seen} className="w-full max-w-[520px] motion-safe:animate-[panel-in_0.35s_ease]">
          <Preview />
        </div>
      </Reveal>
    </div>
  );
}
