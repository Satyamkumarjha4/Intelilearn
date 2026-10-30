"use client";

import { StarIcon } from "lucide-react";
import { useId, useRef } from "react";

import { StarScale } from "@/lib/star-scale";
import { cn } from "@/lib/utils";

type Props = {
  /** The pick as halves (1 to 10), or null before one is made. */
  value: number | null;
  onChange: (halves: number) => void;
  label?: string;
  disabled?: boolean;
};

const SLOTS = [1, 2, 3, 4, 5];

/**
 * Rate yourself, half a star at a time: ten radios in one group, so the keyboard and a screen reader get the whole
 * scale (arrows, Home and End move the pick). Each star is two halves a pointer can hit. The sentence that goes with
 * the pick is read out as it changes.
 */
export function StarRating({ value, onChange, label = "How well do you know this?", disabled = false }: Props) {
  const labelId = useId();
  const sentenceId = useId();
  const radios = useRef(new Map<number, HTMLButtonElement>());
  const picked = StarScale.of(value);
  const focusable = value ?? StarScale.MIN; // the one radio the Tab key lands on

  const onKeyDown = (event: React.KeyboardEvent) => {
    const next = StarScale.move(value, event.key);
    if (next === null || disabled) return;
    event.preventDefault();
    onChange(next);
    radios.current.get(next)?.focus();
  };

  return (
    <div className="flex flex-col items-start gap-2">
      <p id={labelId} className="text-sm font-extrabold text-muted-foreground">
        {label}
      </p>
      <div role="radiogroup" aria-labelledby={labelId} aria-describedby={sentenceId} aria-disabled={disabled} onKeyDown={onKeyDown} className="flex gap-1">
        {SLOTS.map((slot) => (
          <span key={slot} className="relative grid size-11 place-items-center">
            <StarIcon className="size-9 text-muted-foreground/40" aria-hidden="true" />
            <HalfFill slot={slot} value={value} />
            {[slot * 2 - 1, slot * 2].map((halves, side) => (
              <button
                key={halves}
                ref={(node) => {
                  if (node) radios.current.set(halves, node);
                  else radios.current.delete(halves);
                }}
                type="button"
                role="radio"
                aria-checked={value === halves}
                aria-label={StarScale.of(halves)?.label}
                tabIndex={halves === focusable ? 0 : -1}
                disabled={disabled}
                onClick={() => onChange(halves)}
                className={cn(
                  "absolute inset-y-0 w-1/2 cursor-pointer outline-none focus-visible:z-10 focus-visible:ring-3 focus-visible:ring-ring/60 disabled:cursor-default",
                  side === 0 ? "left-0 rounded-l-xl" : "right-0 rounded-r-xl",
                )}
              />
            ))}
          </span>
        ))}
      </div>
      <p id={sentenceId} aria-live="polite" className="min-h-12 max-w-prose text-pretty">
        {picked ? (
          <>
            <span className="font-heading font-semibold">{picked.label}.</span> <span>{picked.sentence}</span>
          </>
        ) : (
          <span className="text-muted-foreground">{StarScale.PROMPT}</span>
        )}
      </p>
    </div>
  );
}

/** A rating shown, not asked for: five stars filled up to the pick. Read aloud as its label, not star by star. */
export function StarsDisplay({ halves, className }: { halves: number; className?: string }) {
  return (
    <span role="img" aria-label={StarScale.of(halves)?.label ?? "No rating"} className={cn("flex gap-0.5", className)}>
      {SLOTS.map((slot) => (
        <span key={slot} className="relative grid size-7 place-items-center">
          <StarIcon className="size-6 text-muted-foreground/40" aria-hidden="true" />
          <HalfFill slot={slot} value={halves} size="size-6" />
        </span>
      ))}
    </span>
  );
}

/** The filled part of one star: the left half, the whole star, or nothing. */
function HalfFill({ slot, value, size = "size-9" }: { slot: number; value: number | null; size?: string }) {
  const left = StarScale.fills(value, slot * 2 - 1);
  const right = StarScale.fills(value, slot * 2);
  if (!left) return null;
  return (
    <StarIcon
      className={cn("pointer-events-none absolute fill-marigold text-marigold-deep motion-safe:transition-[clip-path]", size)}
      style={{ clipPath: right ? undefined : "inset(0 50% 0 0)" }}
      aria-hidden="true"
    />
  );
}
