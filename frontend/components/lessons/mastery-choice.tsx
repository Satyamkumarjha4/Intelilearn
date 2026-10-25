"use client";

import { CheckIcon, ClockIcon, TrophyIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { QuizReview } from "@/components/lessons/quiz-review";
import { SHEET_ICONS } from "@/components/lessons/sheet-icons";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { MasteryBanner, SheetCatalog } from "@/lib/study-sheets";
import type { MaterialKind, QuizResultSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { lessonId: string; result: QuizResultSummary | null; onChosen: () => void };

/** The learner knew (nearly) everything: celebrate it, then let them pick the sheet that would help most instead of a
 *  lesson. The button follows the card picked. */
export function MasteryChoice({ lessonId, result, onChosen }: Props) {
  const [picked, setPicked] = useState<MaterialKind>("revision_sheet");
  const [busy, setBusy] = useState(false);
  const banner = MasteryBanner.of(result);

  const choose = async () => {
    setBusy(true);
    try {
      await lessonsApi.choose(lessonId, picked);
      onChosen();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start that sheet.");
      setBusy(false);
    }
  };

  return (
    <section aria-label="Pick a study sheet" className="flex flex-col gap-6">
      <div className="flex items-center gap-4 rounded-[22px] border-[1.5px] border-marigold/60 bg-marigold-soft px-5 py-4">
        <span className="grid size-14 shrink-0 place-items-center rounded-full bg-marigold text-marigold-foreground shadow-[0_3px_0_var(--marigold-deep)]">
          <TrophyIcon className="size-7" aria-hidden="true" />
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="font-heading text-2xl font-semibold tracking-tight">{banner.headline}</h2>
          <p className="text-marigold-text">{banner.text}</p>
        </div>
      </div>

      <fieldset className="flex flex-col gap-3" disabled={busy}>
        <legend className="mb-3 font-heading text-xl font-semibold">What would help you most?</legend>
        <div className="grid gap-4 md:grid-cols-3">
          {SheetCatalog.all().map((sheet) => {
            const Icon = SHEET_ICONS[sheet.kind];
            const selected = picked === sheet.kind;
            return (
              <label
                key={sheet.kind}
                className={cn(
                  "relative flex cursor-pointer flex-col gap-3 rounded-[22px] border-2 bg-card p-4 motion-safe:transition-[transform,box-shadow,background-color,border-color] has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-default",
                  selected
                    ? "border-primary bg-primary-soft shadow-[0_4px_0_var(--primary-deep)]"
                    : "border-border shadow-[0_4px_0_var(--border)] hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name="sheet"
                  value={sheet.kind}
                  checked={selected}
                  onChange={() => setPicked(sheet.kind)}
                  className="sr-only"
                />
                <span className="flex items-center gap-3">
                  <span
                    className={cn(
                      "grid size-11 shrink-0 place-items-center rounded-2xl",
                      selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                    )}
                  >
                    <Icon className="size-6" aria-hidden="true" />
                  </span>
                  <span className="font-heading text-lg leading-tight font-semibold">{sheet.title}</span>
                </span>
                <span className="text-muted-foreground">{sheet.text}</span>
                <ul className="flex flex-col gap-1.5 text-sm">
                  {sheet.bullets.map((bullet) => (
                    <li key={bullet} className="flex items-start gap-2">
                      <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary-text" aria-hidden="true" />
                      {bullet}
                    </li>
                  ))}
                </ul>
                <span className="mt-auto flex items-center gap-1.5 pt-1 font-mono text-xs font-bold text-muted-foreground">
                  <ClockIcon className="size-3.5" aria-hidden="true" /> {sheet.time}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="flex flex-col items-start gap-1.5">
        <Button size="lg" className="h-10 px-4 text-base" onClick={choose} disabled={busy}>
          {busy ? "Starting…" : SheetCatalog.makeLabel(picked)}
        </Button>
        <p className="text-sm text-muted-foreground">You can add the other sheets afterwards.</p>
      </div>

      {result && <QuizReview lessonId={lessonId} kind="diagnostic" />}
    </section>
  );
}
