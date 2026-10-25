import { LevelReadout } from "@/components/landing/level-readout";
import { DemoOption } from "@/components/landing/demo-option";
import { Difficulty } from "@/components/landing/difficulty";
import { FLAP } from "@/components/lessons/lesson-book";
import { SegmentBar } from "@/components/lessons/segment-bar";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Segment } from "@/lib/deck-session";
import { WALK_PREVIEW } from "@/lib/landing-content";
import { cn } from "@/lib/utils";

const CARD = "gap-0 [--card-spacing:--spacing(5.5)]";
const LABEL = "text-[13px] font-extrabold tracking-wider text-muted-foreground uppercase";
const delay = (seconds: number) => ({ "--d": `${seconds}s` }) as React.CSSProperties;

/** Step 1: the quick check, as the real screen shows it: progress, how hard, a question, an answer picked. */
export function CheckPreview() {
  const { done, total, difficulty, question, options, picked } = WALK_PREVIEW.check;
  const segments: Segment[] = Array.from({ length: total }, (_, n) => (n < done ? "done" : n === done ? "current" : "todo"));
  return (
    <Card data-anim="card" className={CARD}>
      <CardContent>
        <div className="flex">
          <SegmentBar segments={segments} now={done + 1} animate itemClassName="h-2" />
        </div>
        <div className="mt-[18px]">
          <Difficulty {...difficulty} />
        </div>
        <h3 className="mt-2 text-xl">{question}</h3>
        <div className="mt-4 grid gap-2">
          {options.map((option, index) => (
            <DemoOption key={option} preview k={index + 1} state={index === picked ? "picked" : "idle"} animatePick className="py-[11px]">
              {option}
            </DemoOption>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Step 2: "Your starting point", with the level, what is known and what is next. */
export function StartingPointPreview() {
  const { eyebrow, title, level, levelLabel, known, gaps } = WALK_PREVIEW.startingPoint;
  return (
    <Card data-anim="card" className={CARD}>
      <CardContent>
        <p className="font-mono text-[11px] font-medium tracking-widest text-insight-text uppercase">{eyebrow}</p>
        <h3 className="mt-1 text-xl">{title}</h3>
        <div className="mt-5">
          <LevelReadout filled={level} label={levelLabel} animate />
        </div>
        {[
          { heading: "You already know", items: known, variant: "success" as const, from: 0.5 },
          { heading: "We'll focus on", items: gaps, variant: "marigold" as const, from: 0.8 },
        ].map(({ heading, items, variant, from }) => (
          <section key={heading} className="mt-5">
            <h4 className={cn(LABEL, "mb-2.5")}>{heading}</h4>
            <ul className="flex flex-wrap gap-2">
              {items.map((item, n) => (
                <li key={item}>
                  <Badge variant={variant} data-anim="pill" style={delay(from + n * 0.1)} className="rounded-xl px-3 py-1.5 text-sm font-bold">
                    {item}
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}

/** Step 3: a lesson page in its notebook, a flap per page, with a graph that draws itself. Only the shape: no words to read. */
export function BookPreview() {
  const { flaps, active } = WALK_PREVIEW.book;
  const line = "block h-[9px] rounded-[5px] bg-border";
  return (
    <div aria-hidden="true" data-anim="card" className="relative pr-[46px]">
      <div className="absolute top-[26px] right-0 flex w-[52px] flex-col gap-1.5">
        {flaps.map((flap, n) => (
          <span
            key={flap.label}
            data-anim={n === active ? "flap" : undefined}
            className={cn(
              "relative min-h-[78px] border-[1.5px] border-border py-3 pr-1.5 pl-4 text-center text-xs font-extrabold [writing-mode:vertical-rl] rounded-r-xl",
              n === active ? "z-[2] border-l-paper bg-paper text-foreground" : cn("z-0 -translate-x-[5px]", FLAP[flap.tone]),
            )}
          >
            {flap.label}
          </span>
        ))}
      </div>
      <div className="relative z-10 min-h-80 rounded-l-md rounded-r-[18px] border-[1.5px] border-border bg-paper py-[26px] pr-[26px] pl-[54px] shadow-[4px_4px_0_0_var(--paper),4px_4px_0_1.5px_var(--border),8px_8px_0_0_var(--paper),8px_8px_0_1.5px_var(--border)]">
        <span className="pointer-events-none absolute inset-y-[18px] left-3.5 w-[18px] bg-[radial-gradient(circle_at_9px_9px,var(--background)_0_4px,var(--border)_4.5px_6px,transparent_6.5px)] bg-[length:18px_26px] bg-repeat-y" />
        <span className="mb-3.5 block h-4 w-[55%] rounded-md bg-foreground opacity-80" />
        <span className={cn(line, "my-[9px] w-[92%]")} />
        <span className={cn(line, "my-[9px] w-[64%]")} />
        <div className="my-3.5 rounded-xl bg-insight-soft px-3 py-2.5">
          <b className="text-[11px] tracking-widest text-insight-text uppercase">Key idea</b>
          <span className={cn(line, "my-[9px] w-[92%] bg-insight opacity-35")} />
        </div>
        <svg viewBox="0 0 260 90" className="my-2 block h-auto w-full rounded-xl bg-muted p-2">
          <path data-anim="draw" d="M10 80 C 60 20, 120 12, 250 10" fill="none" className="stroke-primary" strokeWidth="4" strokeLinecap="round" />
          <circle data-anim="dot" cx="92" cy="27" r="7" className="fill-marigold stroke-paper" strokeWidth="3" />
          <line x1="10" y1="82" x2="250" y2="82" className="stroke-border" strokeWidth="2" />
        </svg>
        <span className={cn(line, "my-[9px] w-[92%]")} />
      </div>
    </div>
  );
}

const CIRCUMFERENCE = 314.16;

/** Step 4: the test result: a ring that sweeps to the score, and what is worth another look. */
export function ResultPreview() {
  const { percent, eyebrow, title, text, topic, why } = WALK_PREVIEW.result;
  return (
    <Card data-anim="card" className={CARD}>
      <CardContent>
        <div className="flex items-center gap-[18px]">
          <svg viewBox="0 0 120 120" role="img" aria-label={`${percent} percent`} className="size-24 shrink-0">
            <circle cx="60" cy="60" r="50" fill="none" className="stroke-muted" strokeWidth="14" />
            <circle
              data-anim="ring"
              cx="60"
              cy="60"
              r="50"
              fill="none"
              className="stroke-success"
              strokeWidth="14"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - percent / 100)}
              transform="rotate(-90 60 60)"
            />
            <text x="60" y="68" textAnchor="middle" fontSize="26" fontWeight="600" className="fill-foreground font-heading">
              {percent}%
            </text>
          </svg>
          <div>
            <p className="font-mono text-[11px] font-medium tracking-widest text-muted-foreground uppercase">{eyebrow}</p>
            <h3 className="mt-0.5 text-xl">{title}</h3>
            <p className="text-sm text-muted-foreground">{text}</p>
          </div>
        </div>
        <div data-anim="late" className="mt-4 grid gap-2.5 rounded-[18px] border-2 border-border p-4">
          <h4 className={LABEL}>Worth another look</h4>
          <b className="text-base">{topic}</b>
          <p className="text-sm text-muted-foreground">{why}</p>
          <div>
            <span className={buttonVariants({ variant: "marigold", size: "sm" })}>Make a lesson on this</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
