"use client";

import { ArrowRightIcon, ChevronDownIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CostLabel } from "@/components/credits/cost-label";
import { ChoiceCards } from "@/components/lessons/choice-cards";
import { StarRating } from "@/components/lessons/star-rating";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CostSizes } from "@/lib/credits/cost-sizes";
import { lessonsApi } from "@/lib/lessons-api";
import { NewLesson, type SheetPick } from "@/lib/new-lesson";
import type { Entry, Intent } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function NewLessonPage() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [context, setContext] = useState("");
  const [intent, setIntent] = useState<Intent>("lesson");
  const [sheets, setSheets] = useState<SheetPick>("both");
  const [entry, setEntry] = useState<Entry>("diagnostic");
  const [rating, setRating] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!NewLesson.canStart(topic, busy, entry, rating)) return;
    setBusy(true);
    setError(null);
    try {
      const request = NewLesson.request(topic, context, entry, rating, intent, sheets);
      const { lesson_id } = await lessonsApi.create(request.topic, request.context, request.options);
      router.push(`/lessons/${lesson_id}`);
    } catch (err) {
      setError(NewLesson.errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center gap-6 px-4 py-10 text-center">
      <div className="flex flex-col gap-2">
        <h1 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">What do you want to learn?</h1>
        <p className="text-muted-foreground">{NewLesson.intro(entry, intent)}</p>
      </div>

      <form onSubmit={submit} className="flex w-full flex-col gap-5 text-left" noValidate>
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-1.5">
          <label htmlFor="topic" className="sr-only">
            Topic
          </label>
          <input
            id="topic"
            value={topic}
            maxLength={NewLesson.TOPIC_MAX}
            placeholder="Binary search, photosynthesis, quadratic equations…"
            onChange={(e) => setTopic(e.target.value)}
            autoFocus
            autoComplete="off"
            aria-describedby="topic-count"
            className="h-16 w-full rounded-2xl border-2 border-primary bg-card px-5 font-heading text-xl shadow-[0_4px_0_var(--primary-deep)] outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50 sm:text-2xl"
          />
          <p id="topic-count" className="text-right font-mono text-xs text-muted-foreground tabular-nums">
            {NewLesson.counter(topic)}
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-sm font-extrabold text-muted-foreground">Not sure? Try one of these</p>
          <ul className="flex flex-wrap gap-2">
            {NewLesson.EXAMPLES.map((example) => (
              <li key={example}>
                <button
                  type="button"
                  onClick={() => setTopic(example)}
                  className="rounded-full border-2 border-border bg-card px-3.5 py-1 text-sm font-semibold outline-none hover:bg-primary-soft focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <ChoiceCards name="intent" legend="What would you like?" choices={NewLesson.INTENTS} value={intent} onChange={setIntent} disabled={busy}>
          {intent === "sheets" && (
            <div className="mt-1">
              <ChoiceCards name="sheets" legend="Which sheets?" choices={NewLesson.SHEET_CHOICES} value={sheets} onChange={setSheets} disabled={busy} columns={3} />
            </div>
          )}
        </ChoiceCards>

        <ChoiceCards name="entry" legend="How should we find your level?" choices={NewLesson.ENTRIES} value={entry} onChange={setEntry} disabled={busy}>
          {entry === "self_rating" && <StarRating value={rating} onChange={setRating} disabled={busy} />}
        </ChoiceCards>

        <details className="group rounded-2xl border-[1.5px] border-border bg-card">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-2xl px-4 py-3 text-sm font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
            Add a note for us (optional)
            <ChevronDownIcon className="size-4 motion-safe:transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <div className="flex flex-col gap-1.5 px-4 pb-4">
            <label htmlFor="context" className="text-sm text-muted-foreground">
              Anything we should know? An exam coming up, or what you already know.
            </label>
            <Textarea
              id="context"
              value={context}
              maxLength={NewLesson.CONTEXT_MAX}
              rows={3}
              placeholder="For my exam on Friday. I already know arrays."
              onChange={(e) => setContext(e.target.value)}
            />
          </div>
        </details>

        <ol aria-label="What happens next" className="flex items-center justify-center gap-2 text-sm">
          {NewLesson.steps(entry, intent).map((step, index, steps) => (
            <li key={step} className="flex items-center gap-2">
              <span className={cn("flex items-center gap-1.5 rounded-full px-3 py-1 font-extrabold", index === 0 ? "bg-primary-soft text-primary-text" : "bg-muted text-muted-foreground")}>
                <span className="font-mono text-xs">{index + 1}</span>
                <span className="max-sm:hidden">{step}</span>
                <span className="sm:hidden">{index === 0 ? step : ""}</span>
              </span>
              {index < steps.length - 1 && <ArrowRightIcon className="size-4 text-muted-foreground" aria-hidden="true" />}
            </li>
          ))}
        </ol>

        <CostLabel ask={CostSizes.newLesson(entry, intent, NewLesson.sheetsOf(sheets).length)} breakdown className="items-center self-center text-center" />

        <Button type="submit" size="lg" disabled={!NewLesson.canStart(topic, busy, entry, rating)} className="h-12 self-center px-8 text-base">
          {NewLesson.buttonLabel(entry, busy, intent, sheets)}
        </Button>
      </form>
    </main>
  );
}
