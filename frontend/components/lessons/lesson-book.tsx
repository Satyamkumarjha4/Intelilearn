"use client";

import { CheckIcon, Loader2Icon } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import type { FlapTone, LessonBook as Book, NextAction } from "@/lib/lesson-book";
import { cn } from "@/lib/utils";

export const FLAP: Record<FlapTone, string> = {
  primary: "bg-primary-soft text-primary-text",
  marigold: "bg-marigold-soft text-marigold-text",
  insight: "bg-insight-soft text-insight-text",
};

type Props = {
  book: Book;
  next: NextAction;
  onGoTo: (index: number) => void;
  onPrev: () => void;
  onNext: () => void;
  /** Covers the page, e.g. while it is being fixed. */
  overlay?: React.ReactNode;
  /** The lesson itself (the sandboxed iframe). */
  children: React.ReactNode;
};

/**
 * The lesson as a notebook: paper with spiral binding and a margin line, the edge of a stack of pages, and an index
 * flap per page (on the right edge; along the top below 900px). The active flap takes the paper colour and joins the
 * page, the others tuck behind it. The footer turns the pages, and a new page slides in unless the learner asked for
 * less motion.
 */
export function LessonBook({ book, next, onGoTo, onPrev, onNext, overlay, children }: Props) {
  const page = useRef<HTMLDivElement>(null);
  const shown = useRef(book.index);

  useEffect(() => {
    if (shown.current === book.index) return;
    shown.current = book.index;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    page.current?.animate?.([{ transform: "translateX(28px)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 220, easing: "ease-out" });
  }, [book.index]);

  return (
    <div className="relative max-[899px]:pt-9 min-[900px]:pr-12">
      <nav aria-label="Pages of this lesson" className="absolute max-[899px]:inset-x-6 max-[899px]:top-0 min-[900px]:top-8 min-[900px]:right-0">
        {/* No z-index on the nav, so the flaps share a stacking context with the page: the open one is above it
            (joined), the others below it (tucked behind). */}
        <ol className="flex gap-1.5 min-[900px]:flex-col min-[900px]:gap-2">
          {book.flaps.map((flap) => (
            <li key={flap.index} className={cn("flex", flap.active ? "z-20 min-[900px]:-ml-1.5" : "z-0")}>
              <button
                type="button"
                onClick={() => onGoTo(flap.index)}
                aria-current={flap.active ? "page" : undefined}
                className={cn(
                  "relative flex items-center justify-center gap-1.5 border-[1.5px] border-border px-3 py-2 text-sm font-extrabold outline-none motion-safe:transition-[transform,background-color] focus-visible:ring-3 focus-visible:ring-ring/50",
                  "max-[899px]:h-11 max-[899px]:rounded-t-xl max-[899px]:border-b-0",
                  "min-[900px]:w-11 min-[900px]:min-h-28 min-[900px]:rounded-r-xl min-[900px]:border-l-0 min-[900px]:px-0 min-[900px]:py-3 min-[900px]:[writing-mode:vertical-rl]",
                  flap.active
                    ? "bg-paper text-foreground max-[899px]:translate-y-px min-[900px]:w-[3.125rem] min-[900px]:pl-1.5"
                    : cn(FLAP[flap.tone], "max-[899px]:translate-y-1.5 min-[900px]:-translate-x-0.5 hover:max-[899px]:translate-y-0.5 hover:min-[900px]:translate-x-0.5"),
                )}
              >
                {flap.label}
                {flap.read && <CheckIcon className="size-4 shrink-0" aria-label="read" />}
              </button>
            </li>
          ))}
        </ol>
      </nav>

      <div className="relative z-10 flex flex-col overflow-hidden rounded-l-lg rounded-r-[22px] border-[1.5px] border-border bg-paper shadow-[4px_4px_0_0_var(--paper),4px_4px_0_1.5px_var(--border),8px_8px_0_0_var(--paper),8px_8px_0_1.5px_var(--border)]">
        {/* Spiral binding and the margin line */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-[radial-gradient(circle_at_center,var(--background)_0_4px,var(--border)_4.5px_6px,transparent_6.5px)] bg-[length:32px_26px] bg-repeat-y sm:w-9"
        />
        <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-9 w-px bg-insight/25 sm:left-11" />

        <div ref={page} className="relative pr-2 pl-10 sm:pr-4 sm:pl-12">
          {children}
        </div>

        <footer className="relative flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-dashed border-border py-3 pr-4 pl-10 sm:pl-12">
          <Button variant="outline" onClick={onPrev} disabled={book.isFirst}>
            ← Previous page
          </Button>
          <span className="order-last w-full text-center text-sm text-muted-foreground sm:order-none sm:w-auto" aria-live="polite">
            {book.footer}
          </span>
          <Button variant={next.kind === "test" ? "marigold" : "default"} onClick={onNext}>
            {next.label}
          </Button>
        </footer>

        {overlay && (
          <div role="status" className="absolute inset-0 z-20 grid place-items-center bg-paper/90 p-6 text-center">
            <div className="flex flex-col items-center gap-3">
              <Loader2Icon className="size-8 text-primary motion-safe:animate-spin" aria-hidden="true" />
              {overlay}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
