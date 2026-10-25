"use client";

import { CopyIcon, ExternalLinkIcon, RotateCcwIcon, SquareIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { RunModelCalls } from "@/components/console/runs/run-model-calls";
import { RunStatusPill } from "@/components/console/runs/run-status-pill";
import { RunTimelineView } from "@/components/console/runs/run-timeline-view";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { consoleApi } from "@/lib/console-api";
import { Clipboard } from "@/lib/clipboard";
import { RunActions, type ActionResult } from "@/lib/run-actions";
import { RunText } from "@/lib/run-text";
import type { RunDetail } from "@/lib/types";

const actions = new RunActions(consoleApi);
const clipboard = new Clipboard();

type Props = {
  id: string | null;
  detail: RunDetail | null;
  /** "not_found", another message, or null. */
  error: string | null;
  /** Called after Retry or Stop worked; `openRun` is the new run a retry started. */
  onChanged: (openRun: string | null) => void;
  now: Date;
};

function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="border-b px-4 py-3.5">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <h3 className="font-sans text-xs font-extrabold tracking-wider text-muted-foreground uppercase">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function copy(text: string, done: string) {
  void clipboard.copy(text).then((ok) => (ok ? toast.success(done) : toast.error("Couldn't copy. Select the text and copy it yourself.")));
}

/** The open run: status, who and what, time/calls/cost, why it failed, the timeline, model calls and the actions. */
export function RunDetailPanel({ id, detail, error, onChanged, now }: Props) {
  const [stopping, setStopping] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!id) {
    return (
      <Card className="p-6 text-center text-sm text-muted-foreground">
        Pick a run to see its timeline, model calls and what went wrong.
      </Card>
    );
  }
  if (!detail) {
    if (error) {
      return (
        <Card className="p-6 text-center text-sm" role="alert">
          {error === "not_found" ? "That run isn't there (any more). It may have been deleted." : error}
        </Card>
      );
    }
    return (
      <Card className="gap-3 p-4" aria-busy="true" aria-label="Loading the run">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-32 w-full" />
      </Card>
    );
  }

  const status = RunText.status(detail.status);
  const live = RunText.isActive(detail.status);
  const settle = async (action: Promise<ActionResult>) => {
    setBusy(true);
    const result = await action;
    setBusy(false);
    if (result.ok) {
      toast.success(result.message);
      onChanged(result.runId);
    } else {
      toast.error(result.message);
    }
  };

  return (
    <Card className="gap-0 p-0" aria-label="Run details">
      <header className="grid gap-2 border-b px-4 py-4">
        <div className="flex items-center justify-between gap-2">
          <RunStatusPill {...status} />
          <span className="font-mono text-xs text-muted-foreground" title={detail.id}>
            run {RunText.shortId(detail.id)}
          </span>
        </div>
        <h2 className="text-xl">{detail.topic}</h2>
        <p className="text-sm font-semibold text-muted-foreground">
          {detail.learner_name} · {RunText.job(detail.graph)} · started{" "}
          <time dateTime={detail.created_at} title={RunText.exact(detail.created_at)}>
            {RunText.ago(detail.created_at, now)}
          </time>
        </p>
        <dl className="mt-1 grid grid-cols-3 gap-2">
          {[
            ["Time", RunText.duration(detail.duration_s)],
            ["Calls", String(detail.calls)],
            ["Cost", RunText.cost(detail.cost)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg bg-muted px-2.5 py-2">
              <dt className="text-[11px] font-extrabold tracking-wide text-muted-foreground uppercase">{label}</dt>
              <dd className="font-mono text-[13.5px] font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </header>

      {detail.error && (
        <Section
          title="What went wrong"
          action={
            <Button variant="ghost" size="xs" onClick={() => copy(detail.error, "Copied the error")} aria-label="Copy the error text">
              <CopyIcon /> Copy
            </Button>
          }
        >
          <pre className="rounded-xl bg-destructive-soft px-3 py-2.5 font-mono text-xs break-words whitespace-pre-wrap text-destructive-text">
            {detail.error}
          </pre>
        </Section>
      )}

      <Section
        title="Timeline"
        action={
          live && (
            <span className="inline-flex items-center gap-1.5 text-xs font-bold text-primary-text">
              <span aria-hidden="true" className="size-2 rounded-full bg-primary motion-safe:animate-pulse" /> Live
            </span>
          )
        }
      >
        <RunTimelineView steps={detail.timeline} runDurationS={detail.duration_s} />
      </Section>

      <Section title={`Model calls · last ${detail.model_calls.length}`}>
        <RunModelCalls calls={detail.model_calls} />
      </Section>

      <div className="flex flex-wrap gap-2 px-4 py-3.5">
        {detail.can_retry && (
          <Button size="sm" disabled={busy} onClick={() => void settle(actions.retry(detail.id))}>
            <RotateCcwIcon /> Retry from checkpoint
          </Button>
        )}
        {detail.can_cancel && (
          <Button size="sm" variant="destructive" disabled={busy} onClick={() => setStopping(true)}>
            <SquareIcon /> Stop run
          </Button>
        )}
        <a
          href={`/lessons/${detail.lesson_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          <ExternalLinkIcon /> Open lesson<span className="sr-only"> (opens in a new tab)</span>
        </a>
        <Button size="sm" variant="outline" onClick={() => copy(detail.id, "Copied the run ID")}>
          <CopyIcon /> Copy run ID
        </Button>
      </div>

      <ConfirmDialog
        open={stopping}
        onOpenChange={setStopping}
        title="Stop this run?"
        description={`The run for "${detail.topic}" stops after its current step and the lesson is marked as failed, so ${detail.learner_name} can retry it.`}
        confirmLabel="Stop run"
        cancelLabel="Keep it running"
        onConfirm={() => settle(actions.cancel(detail.id))}
      />
    </Card>
  );
}
