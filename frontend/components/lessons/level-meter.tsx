import { cn } from "@/lib/utils";

type Props = {
  filled: number;
  total: number;
  label: string;
  /** The filled segments grow in one after another (the landing page's walkthrough plays it). */
  animate?: boolean;
  className?: string;
};

/** A learner's level as a row of segments, in the AI's colour (grape). */
export function LevelMeter({ filled, total, label, animate, className }: Props) {
  return (
    <div role="img" aria-label={`Level ${filled} of ${total}: ${label}`} className={cn("flex gap-1.5", className)}>
      {Array.from({ length: total }, (_, n) => (
        <span
          key={n}
          data-anim={animate && n < filled ? "grow" : undefined}
          style={animate ? ({ "--d": `${n * 0.15}s` } as React.CSSProperties) : undefined}
          className={cn("h-2.5 flex-1 origin-left rounded-full", n < filled ? "bg-insight" : "bg-insight-soft")}
        />
      ))}
    </div>
  );
}
