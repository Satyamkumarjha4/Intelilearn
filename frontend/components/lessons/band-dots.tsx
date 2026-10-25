import type { Dot } from "@/lib/starting-point";
import { cn } from "@/lib/utils";

/** How a dot looks. A diagnostic is not an exam, so a miss is amber, never red, and "I don't know" is an empty,
 *  dashed dot: it is not a failure. */
const DOT: Record<Dot, { className: string; label: string }> = {
  right: { className: "bg-success", label: "right" },
  wrong: { className: "border-2 border-marigold bg-marigold-soft", label: "not yet" },
  unsure: { className: "border-2 border-dashed border-muted-foreground bg-transparent", label: "I don't know" },
};

export const DOT_LEGEND = "Green: right · Amber: not yet · Dashed: you said “I don't know” (that helps us)";

/** The dots of one band, one per question. */
export function BandDots({ dots }: { dots: Dot[] }) {
  return (
    <span className="flex gap-1.5">
      {dots.map((dot, n) => (
        <span key={n} role="img" aria-label={DOT[dot].label} className={cn("size-3.5 rounded-full", DOT[dot].className)} />
      ))}
    </span>
  );
}
