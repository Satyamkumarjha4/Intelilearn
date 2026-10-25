"use client";

import { useState } from "react";

import { BandDots, DOT_LEGEND } from "@/components/lessons/band-dots";
import { LevelMeter } from "@/components/lessons/level-meter";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Chips } from "@/lib/chips";
import { StartingPoint } from "@/lib/starting-point";
import type { Assessment, QuizResultSummary, QuizReview } from "@/lib/types";


type Props = { assessment: Assessment; result: QuizResultSummary | null; review: QuizReview | null };

/** What the quick check told us about the learner, in the AI's colour (grape): their level, the topics they have and
 *  lack, and where the lesson will begin. */
export function StartingPointCard({ assessment, result, review }: Props) {
  const view = StartingPoint.of(assessment, result, review);
  return (
    <Card className="border-insight/40 bg-card">
      <CardContent className="flex flex-col gap-5 px-5">
        <div className="flex flex-col gap-1">
          <p className="font-mono text-xs font-bold tracking-wider text-insight-text uppercase">Your starting point</p>
          <p className="font-heading text-xl font-semibold">{view.level.label}</p>
          <LevelMeter filled={view.level.filled} total={view.level.total} label={view.level.label} className="mt-1" />
        </div>

        {view.bands.length > 0 && (
          <section aria-label="Your quick check" className="flex flex-col gap-2">
            <h2 className="text-sm font-extrabold">How your quick check went</h2>
            <ul className="flex flex-col gap-1.5">
              {view.bands.map((band) => (
                <li key={band.band} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">{band.label}</span>
                  <BandDots dots={band.dots} />
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">{DOT_LEGEND}</p>
          </section>
        )}

        <ChipSection title="You already know" topics={view.known} variant="success" />
        <ChipSection title="We'll focus on" topics={view.gaps} variant="marigold" />

        {view.startPoint && (
          <section aria-label="Where your lesson begins" className="flex flex-col gap-1.5 rounded-xl border-2 border-dashed border-insight/50 bg-insight-soft px-3 py-2.5">
            <h2 className="text-sm font-extrabold text-insight-text">Where your lesson begins</h2>
            <p className="text-sm">{view.startPoint}</p>
          </section>
        )}

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-extrabold">How sure we are</span>
            <span className="text-muted-foreground">{view.confidence.label}</span>
          </div>
          <div
            role="progressbar"
            aria-label="How sure we are about your level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(view.confidence.fraction * 100)}
            className="h-2.5 w-full overflow-hidden rounded-full bg-insight-soft"
          >
            <div className="h-full rounded-full bg-insight motion-safe:transition-all" style={{ width: `${view.confidence.fraction * 100}%` }} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/** A heading and its topics as chips (sentence case): the first few, then "+N more" which opens the rest in place. */
function ChipSection({ title, topics, variant }: { title: string; topics: string[]; variant: "success" | "marigold" }) {
  const [expanded, setExpanded] = useState(false);
  if (topics.length === 0) return null;
  const { shown, hidden } = Chips.collapse(topics, Chips.LIMIT, expanded);
  const collapsible = Chips.collapsible(topics, Chips.LIMIT);
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h2 className="text-sm font-extrabold">{title}</h2>
      <ul className="flex flex-wrap gap-1.5">
        {shown.map((topic) => (
          <li key={topic}>
            <Badge variant={variant}>{Chips.sentence(topic)}</Badge>
          </li>
        ))}
        {collapsible && (
          <li>
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((open) => !open)}
              className="rounded-full border border-dashed border-border px-2 py-0.5 text-xs font-bold text-muted-foreground outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {expanded ? "Show fewer" : `+${hidden} more`}
            </button>
          </li>
        )}
      </ul>
    </section>
  );
}
