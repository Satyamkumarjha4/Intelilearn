"use client";

import { CheckCircle2Icon, CircleDashedIcon, Loader2Icon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PipelineModel } from "@/lib/pipeline";

type Props = { pipeline: PipelineModel; title: string; onCancel?: () => void };

/** Live steps of whatever the system is doing for the learner right now. */
export function PipelineProgress({ pipeline, title, onCancel }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">
          <h1>{title}</h1>
        </CardTitle>
        <CardDescription>This takes a little while. You can leave this page; it keeps going.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ol className="flex flex-col gap-3" aria-live="polite">
          {pipeline.steps.map((step) => (
            <li key={step.label} className="flex items-start gap-3">
              {step.status === "done" ? (
                <CheckCircle2Icon className="mt-0.5 size-5 text-emerald-600" aria-label="done" />
              ) : step.status === "running" ? (
                <Loader2Icon className="mt-0.5 size-5 animate-spin" aria-label="in progress" />
              ) : (
                <CircleDashedIcon className="mt-0.5 size-5 text-muted-foreground" aria-label="waiting" />
              )}
              <div className="flex flex-col">
                <span className={step.status === "pending" ? "text-muted-foreground" : "font-medium"}>{step.label}</span>
                {step.note && <span className="text-sm text-muted-foreground">{step.note}</span>}
              </div>
            </li>
          ))}
        </ol>
        {pipeline.warnings.length > 0 && (
          <ul className="list-disc pl-5 text-sm text-muted-foreground">
            {pipeline.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}
        {onCancel && (
          <Button variant="outline" className="self-start" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
