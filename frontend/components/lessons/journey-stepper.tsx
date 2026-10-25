import { CheckIcon, XIcon } from "lucide-react";

import type { JourneyStep } from "@/lib/journey";
import { cn } from "@/lib/utils";

/**
 * Where the learner is on the way from the first quick check to revisiting what they got wrong. On a narrow screen
 * only the current step keeps its label (the others are still read out by screen readers).
 */
export function JourneyStepper({ steps }: { steps: JourneyStep[] }) {
  return (
    <ol aria-label="Your journey" className="flex items-center gap-1.5 sm:gap-2">
      {steps.map((step, index) => (
        <li
          key={step.label}
          aria-current={step.state === "now" ? "step" : undefined}
          // The current step keeps its full label; the others share what is left, so on a phone they shrink to a dot.
          className={cn("flex items-center gap-1.5 sm:gap-2", index < steps.length - 1 && (step.state === "now" ? "shrink-0 sm:flex-1" : "min-w-0 flex-1"))}
        >
          <span
            className={cn(
              "grid size-7 shrink-0 place-items-center rounded-full border-2 font-mono text-xs font-bold",
              step.state === "done" && "border-primary-soft bg-primary-soft text-primary-text",
              step.state === "now" && !step.failed && "border-primary bg-primary text-primary-foreground",
              step.state === "now" && step.failed && "border-destructive bg-destructive-soft text-destructive-text",
              step.state === "todo" && "border-border bg-card text-muted-foreground",
            )}
          >
            {step.state === "done" ? (
              <CheckIcon className="size-4" aria-hidden="true" />
            ) : step.failed ? (
              <XIcon className="size-4" aria-hidden="true" />
            ) : (
              index + 1
            )}
          </span>
          <span
            className={cn(
              "text-sm whitespace-nowrap",
              step.state === "now" ? "font-extrabold text-foreground" : "sr-only font-semibold text-muted-foreground sm:not-sr-only",
              step.failed && "text-destructive-text",
            )}
          >
            {step.label}
            <span className="sr-only">
              {step.failed ? " (stopped here)" : step.state === "done" ? " (done)" : step.state === "now" ? " (you are here)" : ""}
            </span>
          </span>
          {index < steps.length - 1 && (
            <span aria-hidden="true" className={cn("h-0.5 min-w-3 flex-1 rounded-full", step.state === "done" ? "bg-primary-soft" : "bg-border")} />
          )}
        </li>
      ))}
    </ol>
  );
}
