"use client";

import { ArrowLeftIcon, ArrowRightIcon, CheckIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Reveal } from "@/components/landing/reveal";
import { useAutoplay } from "@/components/landing/use-autoplay";
import { usePrefersReducedMotion } from "@/components/landing/use-reduced-motion";
import { Button } from "@/components/ui/button";
import { Autoplay } from "@/lib/autoplay";
import { PATH_SLIDES, type PathSlide, type Tone } from "@/lib/landing-content";
import { ScorePaths } from "@/lib/score-paths";
import { SlideCycle } from "@/lib/slide-cycle";
import { cn } from "@/lib/utils";

const GAP = 16;
const delay = (seconds: number) => ({ "--d": `${seconds}s` }) as React.CSSProperties;

const TONE: Record<Tone, { tab: string; dot: string; slide: string; done: string; avatar: string }> = {
  marigold: {
    tab: "aria-selected:border-marigold-deep aria-selected:bg-marigold-soft aria-selected:shadow-[0_4px_0_var(--marigold-deep)]",
    dot: "bg-marigold",
    slide: "border-marigold bg-marigold-soft",
    done: "border-marigold bg-marigold text-marigold-foreground",
    avatar: "bg-marigold-soft text-marigold-text",
  },
  primary: {
    tab: "aria-selected:border-primary aria-selected:bg-primary-soft aria-selected:shadow-[0_4px_0_var(--primary)]",
    dot: "bg-primary",
    slide: "border-primary bg-primary-soft",
    done: "border-primary bg-primary text-primary-foreground",
    avatar: "bg-primary-soft text-primary-text",
  },
  insight: {
    tab: "aria-selected:border-insight aria-selected:bg-insight-soft aria-selected:shadow-[0_4px_0_var(--insight)]",
    dot: "bg-insight",
    slide: "border-insight bg-insight-soft",
    done: "border-insight bg-insight text-card",
    avatar: "bg-insight-soft text-insight-text",
  },
};

function Slide({ slide, active, play }: { slide: PathSlide; active: boolean; play: boolean }) {
  const tone = TONE[slide.tone];
  const { example } = slide;
  return (
    <div
      role="tabpanel"
      id={`path-slide-${slide.id}`}
      aria-labelledby={`path-tab-${slide.id}`}
      aria-hidden={!active}
      data-play={active && play}
      className={cn("grid min-w-0 snap-start grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-7 rounded-[26px] border-2 p-[30px] max-[900px]:grid-cols-1 max-[900px]:p-[22px]", tone.slide)}
    >
      <div>
        <span data-anim="slide" className="block font-mono text-[13px] text-muted-foreground">
          If you score <b className="font-heading text-[22px] font-semibold text-foreground">{slide.ifYouScore}</b>
        </span>
        <div data-anim="slide" style={delay(0.05)} role="img" aria-label={`${example.score} of ${ScorePaths.TOTAL} right`} className="mt-3 flex gap-1">
          {ScorePaths.dots(example.score).map((right, n) => (
            <i
              key={n}
              data-anim="slide-dot"
              style={delay(n * 0.04)}
              className={cn("size-5 rounded-full border-2 max-[560px]:size-[15px]", right ? "border-success bg-success" : "border-marigold bg-marigold-soft")}
            />
          ))}
        </div>
        <h3 data-anim="slide" style={delay(0.1)} className="mt-4 text-[26px] max-[900px]:text-[22px]">
          {slide.heading}
        </h3>
        <p data-anim="slide" style={delay(0.15)} className="mt-2 max-w-[48ch] text-base opacity-85">
          {slide.text}
        </p>
        <ol data-anim="slide" style={delay(0.2)} className="relative mt-5 grid gap-2.5 before:absolute before:top-4 before:bottom-4 before:left-[15px] before:w-[3px] before:rounded-sm before:bg-border">
          {slide.steps.map((step, n) => (
            <li key={step} className="relative flex items-center gap-3 font-extrabold">
              <span aria-hidden="true" className={cn("grid size-8 shrink-0 place-items-center rounded-[10px] border-2 border-border bg-card text-[13px]", n === 0 && tone.done)}>
                {n === 0 ? <CheckIcon className="size-4" strokeWidth={3} /> : n + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </div>
      <aside data-anim="slide" style={delay(0.25)} aria-label={`Example: ${example.name}`} className="grid content-start gap-3.5 rounded-[22px] bg-card p-[22px] shadow-card">
        <div className="flex items-center gap-3">
          <span aria-hidden="true" className={cn("grid size-[46px] shrink-0 place-items-center rounded-full text-lg font-extrabold", tone.avatar)}>
            {example.initial}
          </span>
          <div className="min-w-0 flex-1">
            <b className="block text-[17px]">{example.name}</b>
            <small className="text-[13px] font-bold text-muted-foreground">{example.meta}</small>
          </div>
          <span className="inline-flex items-center rounded-full bg-muted px-3 py-1 text-[12.5px] font-extrabold text-muted-foreground">Example</span>
        </div>
        <div className="flex items-center justify-between rounded-2xl bg-muted px-3.5 py-2.5 font-extrabold">
          <span className="text-[13.5px] text-muted-foreground">Quick check</span>
          <b>{example.score} / {ScorePaths.TOTAL}</b>
        </div>
        <div className="rounded-2xl border-2 border-dashed border-insight bg-insight-soft p-4">
          <p className="mb-1 font-mono text-[11px] font-medium tracking-widest text-insight-text uppercase">{example.lead}</p>
          <p className="font-bold">{example.text}</p>
        </div>
      </aside>
    </div>
  );
}

/**
 * "Three ways forward": a tab, a slide and a dot for each score range. The slides sit in a scroll-snap track, so a
 * swipe moves them; tabs, arrows, dots and the ← → keys move them too, wrapping at the ends. The slide in view pops its
 * contents in, once the section has scrolled into view. It also moves on by itself every six seconds (see `Autoplay`),
 * except while the mouse is over it, keyboard focus is in it, it is being touched, or it is less than 30% on screen.
 */
export function PathsCarousel() {
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState(false);
  // Which turn of the timer the progress bar is on: it starts over whenever the slide changes or is chosen again.
  const [cycle, setCycle] = useState(0);
  // The track is announced politely after a change the visitor made, never for the ones that happen by themselves.
  const [live, setLive] = useState<"off" | "polite">("off");
  const lessMotion = usePrefersReducedMotion();
  const track = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const settle = useRef<number>(0);
  const shown = useRef(0);
  const count = PATH_SLIDES.length;

  useEffect(() => () => window.clearTimeout(settle.current), []);

  const show = (next: number) => {
    const target = ((next % count) + count) % count;
    shown.current = target;
    setIndex(target);
    setCycle((turn) => turn + 1);
    const slide = track.current?.children[target] as HTMLElement | undefined;
    if (slide) track.current?.scrollTo({ left: slide.offsetLeft, behavior: lessMotion ? "auto" : "smooth" });
  };

  const autoplay = useAutoplay({
    onAdvance: () => {
      setLive("off");
      show(shown.current + 1);
    },
    enabled: !lessMotion,
    target: root,
  });

  /** The visitor chose a slide (tab, dot, arrow, key or swipe): go there and give it a whole interval. */
  const go = (next: number) => {
    setLive("polite");
    show(next);
    autoplay.restart();
  };

  // A swipe only moves the track: once it stops, work out which slide it stopped on.
  const onScroll = () => {
    window.clearTimeout(settle.current);
    settle.current = window.setTimeout(() => {
      const element = track.current;
      if (!element) return;
      const landed = SlideCycle.fromScroll(element.scrollLeft, element.clientWidth, GAP, count);
      if (landed !== shown.current) go(landed);
    }, 90);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    const onTab = target.getAttribute("role") === "tab";
    if (!onTab && target !== track.current) return; // the arrow buttons and dots keep the keys they have
    const next = SlideCycle.byKey(event.key, index, count);
    if (next === null) return;
    event.preventDefault(); // the focused track would also scroll itself, on top of the slide we show
    go(next);
    // Tabs take the focus with them (only the tab in view is in the tab order), so the next arrow press lands too.
    if (onTab) root.current?.querySelector<HTMLElement>(`#path-tab-${PATH_SLIDES[next].id}`)?.focus();
  };

  return (
    <Reveal onShow={() => setSeen(true)} className="mt-7">
      <div ref={root} onKeyDown={onKeyDown} {...autoplay.handlers}>
        <div role="tablist" aria-label="Score ranges" className="flex flex-wrap gap-2">
          {PATH_SLIDES.map((slide, n) => (
            <button
              key={slide.id}
              type="button"
              role="tab"
              id={`path-tab-${slide.id}`}
              aria-selected={n === index}
              aria-controls={`path-slide-${slide.id}`}
              tabIndex={n === index ? 0 : -1}
              onClick={() => go(n)}
              className={cn(
                "relative inline-flex items-center gap-2 overflow-hidden rounded-[14px] border-2 border-border bg-card px-4 py-[9px] font-extrabold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                "motion-safe:transition-transform aria-selected:-translate-y-0.5 aria-selected:text-foreground",
                TONE[slide.tone].tab,
              )}
            >
              <i aria-hidden="true" className={cn("size-3 rounded-full", TONE[slide.tone].dot)} />
              {slide.tab}
              {n === index && !lessMotion && (
                // Fills over the interval along the tab's bottom edge; paused with the player, restarted by `cycle`.
                <span
                  key={cycle}
                  aria-hidden="true"
                  style={{ animation: `tick ${Autoplay.INTERVAL_MS}ms linear forwards`, animationPlayState: autoplay.paused ? "paused" : "running" }}
                  className="absolute bottom-0 left-0 h-1 w-0 bg-current opacity-55"
                />
              )}
            </button>
          ))}
        </div>

        <div
          ref={track}
          role="group"
          aria-roledescription="carousel"
          aria-label="What each score leads to"
          aria-live={live}
          tabIndex={0}
          onScroll={onScroll}
          className="relative mt-4 grid auto-cols-[100%] grid-flow-col snap-x snap-mandatory gap-4 overflow-x-auto rounded-[26px] pb-2 [scrollbar-width:none] focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none motion-safe:scroll-smooth [&::-webkit-scrollbar]:hidden"
        >
          {PATH_SLIDES.map((slide, n) => (
            <Slide key={slide.id} slide={slide} active={n === index} play={seen} />
          ))}
        </div>

        <div className="mt-4 flex items-center justify-center gap-4">
          <Button variant="outline" size="icon-lg" aria-label="Previous slide" onClick={() => go(SlideCycle.previous(index, count))}>
            <ArrowLeftIcon />
          </Button>
          <div className="flex gap-0.5">
            {PATH_SLIDES.map((slide, n) => (
              <button key={slide.id} type="button" aria-label={`Show ${slide.tab}`} aria-current={n === index} onClick={() => go(n)} className="group grid h-6 place-items-center rounded-full px-1 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                <span className={cn("block h-2.5 rounded-full motion-safe:transition-[width,background-color]", n === index ? "w-7 bg-primary" : "w-2.5 bg-border group-hover:bg-muted-foreground/40")} />
              </button>
            ))}
          </div>
          <Button variant="outline" size="icon-lg" aria-label="Next slide" onClick={() => go(SlideCycle.next(index, count))}>
            <ArrowRightIcon />
          </Button>
        </div>
      </div>
    </Reveal>
  );
}
