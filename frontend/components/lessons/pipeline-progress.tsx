"use client";

import { CheckCircle2Icon, CircleIcon, Loader2Icon } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { SmallNotes } from "@/components/lessons/small-notes";
import { useNow } from "@/components/lessons/use-now";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { LessonStatus } from "@/lib/lesson-status";
import { Elapsed, type PipelineModel } from "@/lib/pipeline";
import { StopControl } from "@/lib/stop-control";
import { cn } from "@/lib/utils";

type Props = {
  pipeline: PipelineModel;
  /** The small line above the heading, e.g. "Building your lesson". */
  title: string;
  /** Stops the build. Without it there is no Stop button. */
  onCancel?: () => void | Promise<void>;
  className?: string;
};

/** The building screen's main card: what is happening now, how far along it is, and every step with how long it took. */
export function PipelineProgress({ pipeline, title, onCancel, className }: Props) {
  const [stopping, setStopping] = useState(false);
  const now = useNow(true);
  const steps = pipeline.stepsAt(now);
  const percent = pipeline.percent;
  const notes = pipeline.notes;
  const stop = StopControl.of({ canStop: Boolean(onCancel), open: stopping });
  const started = pipeline.startedAt !== null ? LessonStatus.ago(new Date(pipeline.startedAt).toISOString(), now) : "";

  return (
    <Card className={className}>
      <CardContent className="flex flex-col gap-5 px-5">
        <div className="flex flex-col gap-1.5" aria-live="polite">
          <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">{title}</p>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">{pipeline.headline}</h1>
          <p className="text-sm text-muted-foreground">You can leave this page; we&apos;ll keep going.</p>
        </div>

        {pipeline.measurable ? (
          <div className="flex flex-col gap-2">
            <p className="font-heading text-4xl font-semibold tabular-nums">{percent}%</p>
            <Progress value={percent / 100} label="How much is built" />
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <Progress indeterminate label="Getting started" />
            <p className="text-sm text-muted-foreground">Usually takes under a minute</p>
          </div>
        )}

        {pipeline.recovered && (
          <p role="status" className="rounded-xl bg-marigold-soft px-3 py-2 text-sm text-marigold-text">
            One step took a second try. Nothing you need to do.
          </p>
        )}

        <ol className="flex flex-col gap-3">
          {steps.map((step) => (
            <li key={step.key} className="flex items-start gap-3" aria-current={step.status === "running" ? "step" : undefined}>
              {step.status === "done" ? (
                <CheckCircle2Icon className="mt-0.5 size-5 shrink-0 text-success" aria-label="done" />
              ) : step.status === "running" ? (
                <Loader2Icon className="mt-0.5 size-5 shrink-0 text-primary motion-safe:animate-spin" aria-label="in progress" />
              ) : (
                <CircleIcon className="mt-0.5 size-5 shrink-0 text-border" aria-label="waiting" />
              )}
              <div className="flex min-w-0 flex-1 flex-col">
                <span className={cn("font-semibold", step.status === "pending" && "font-medium text-muted-foreground")}>{step.label}</span>
                {step.detail && <span className="text-sm text-muted-foreground">{step.detail}</span>}
              </div>
              {step.elapsedMs !== null && (
                <span className="mt-0.5 font-mono text-xs text-muted-foreground tabular-nums">{Elapsed.format(step.elapsedMs)}</span>
              )}
            </li>
          ))}
        </ol>

        <SmallNotes notes={notes} />

        {(stop.showButton || stop.mountDialog || started) && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-dashed border-border pt-4">
            <p className="text-sm text-muted-foreground">{started && `Started ${started}`}</p>
            {stop.showButton && (
              <Button variant="outline" size="sm" className="text-muted-foreground" onClick={() => setStopping(true)}>
                Stop building
              </Button>
            )}
            {stop.mountDialog && (
              <ConfirmDialog
                open={stopping}
                onOpenChange={setStopping}
                title="Stop building?"
                description={stop.description}
                confirmLabel="Stop building"
                cancelLabel="Keep building"
                confirmDisabled={!stop.canConfirm}
                onConfirm={() => onCancel?.()}
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
