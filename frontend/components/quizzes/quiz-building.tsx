"use client";

import { CheckCircle2Icon, CircleIcon, Loader2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { QuizProgress } from "@/lib/quiz-progress";
import type { NodeStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  nodeStatus: Record<string, NodeStatus>;
  /** The small line above the heading. */
  title?: string;
  heading?: string;
  /** Stops the run. Without it there is no button. */
  onCancel?: () => void;
  cancelling?: boolean;
};

/** The wait while a quiz is made or a new try is written: four plain steps, and a way to stop. */
export function QuizBuilding({ nodeStatus, title = "Making your quiz", heading = "Getting your questions ready", onCancel, cancelling = false }: Props) {
  const steps = QuizProgress.steps(nodeStatus);
  return (
    <Card>
      <CardContent className="flex flex-col gap-5 px-5">
        <div className="flex flex-col gap-1.5" aria-live="polite">
          <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">{title}</p>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">{heading}</h1>
          <p className="text-sm text-muted-foreground">You can leave this page; we&apos;ll keep going.</p>
        </div>
        <Progress indeterminate label="Getting started" />
        <ol className="flex flex-col gap-2">
          {steps.map((step) => (
            <li key={step.label} className={cn("flex items-center gap-3 text-sm", step.state === "waiting" ? "text-muted-foreground" : "font-semibold")}>
              {step.state === "done" ? (
                <CheckCircle2Icon className="size-5 text-success" aria-label="Done" />
              ) : step.state === "active" ? (
                <Loader2Icon className="size-5 text-primary motion-safe:animate-spin" aria-label="In progress" />
              ) : (
                <CircleIcon className="size-5" aria-label="Waiting" />
              )}
              {step.label}
            </li>
          ))}
        </ol>
        {onCancel && (
          <div>
            <Button variant="outline" onClick={onCancel} disabled={cancelling}>
              {cancelling ? "Stopping…" : "Stop"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
