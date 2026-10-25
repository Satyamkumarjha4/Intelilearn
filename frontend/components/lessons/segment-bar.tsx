import type { Segment } from "@/lib/deck-session";
import { cn } from "@/lib/utils";

type Props = {
  segments: Segment[];
  /** The place, 1-based, for assistive technology. */
  now: number;
  /** Segments that are done fill in one after another (the landing page's walkthrough plays it). */
  animate?: boolean;
  className?: string;
  /** Overrides a segment's classes, e.g. a thinner bar. */
  itemClassName?: string;
};

/** The row of segments over a deck of cards: done, the current one, and those still to come. */
export function SegmentBar({ segments, now, animate, className, itemClassName }: Props) {
  return (
    <div role="progressbar" aria-label="Progress" aria-valuemin={1} aria-valuemax={segments.length} aria-valuenow={now} className={cn("flex flex-1 gap-1.5", className)}>
      {segments.map((segment, n) => (
        <span
          key={n}
          data-anim={animate && segment === "done" ? "seg" : undefined}
          style={animate ? ({ "--d": `${0.15 + n * 0.1}s` } as React.CSSProperties) : undefined}
          className={cn(
            "h-2.5 flex-1 rounded-full",
            segment === "done" && "bg-primary",
            segment === "current" && "bg-primary-soft ring-2 ring-primary",
            segment === "todo" && "bg-muted",
            itemClassName,
          )}
        />
      ))}
    </div>
  );
}
