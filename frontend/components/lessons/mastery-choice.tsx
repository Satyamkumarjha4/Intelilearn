"use client";

import { CheckIcon, ClockIcon, GraduationCapIcon, ScrollTextIcon, TrophyIcon, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { QuizReview } from "@/components/lessons/quiz-review";
import { SHEET_ICONS } from "@/components/lessons/sheet-icons";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { MasteryOptions } from "@/lib/mastery-options";
import { MasteryBanner, SheetCatalog } from "@/lib/study-sheets";
import type { LessonDetail, MasteryPick, MaterialKind } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { lesson: Pick<LessonDetail, "id" | "mastery_options" | "results">; onChosen: () => void };

const PICK_ICONS: Record<MasteryPick, LucideIcon> = { lesson: GraduationCapIcon, sheets: ScrollTextIcon };

/** The learner knew (nearly) everything: celebrate it, then let them choose what happens next. A lesson that was
 *  already waiting at the older choice keeps the three sheets it was offered. The button follows the card picked. */
export function MasteryChoice({ lesson, onChosen }: Props) {
  const result = lesson.results.diagnostic;
  const banner = MasteryBanner.of(result);
  const legacy = MasteryOptions.legacy(lesson);

  return (
    <section aria-label={legacy ? "Pick a study sheet" : "What next?"} className="flex flex-col gap-6">
      <div className="flex items-center gap-4 rounded-[22px] border-[1.5px] border-marigold/60 bg-marigold-soft px-5 py-4">
        <span className="grid size-14 shrink-0 place-items-center rounded-full bg-marigold text-marigold-foreground shadow-[0_3px_0_var(--marigold-deep)]">
          <TrophyIcon className="size-7" aria-hidden="true" />
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="font-heading text-2xl font-semibold tracking-tight">{banner.headline}</h2>
          <p className="text-marigold-text">{banner.text}</p>
        </div>
      </div>

      {legacy ? <ThreeSheets lessonId={lesson.id} onChosen={onChosen} /> : <TwoOptions lessonId={lesson.id} onChosen={onChosen} />}

      {result && <QuizReview lessonId={lesson.id} kind="diagnostic" />}
    </section>
  );
}

type CardProps = { name: string; value: string; selected: boolean; onSelect: () => void; icon: LucideIcon; title: string; text: string; bullets: string[]; time: string };

/** One card of a choice: a radio button that looks like a card, picked with the mouse or the keyboard. */
function ChoiceCard({ name, value, selected, onSelect, icon: Icon, title, text, bullets, time }: CardProps) {
  return (
    <label
      className={cn(
        "relative flex cursor-pointer flex-col gap-3 rounded-[22px] border-2 bg-card p-4 motion-safe:transition-[transform,box-shadow,background-color,border-color] has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-default",
        selected ? "border-primary bg-primary-soft shadow-[0_4px_0_var(--primary-deep)]" : "border-border shadow-[0_4px_0_var(--border)] hover:bg-muted",
      )}
    >
      <input type="radio" name={name} value={value} checked={selected} onChange={onSelect} className="sr-only" />
      <span className="flex items-center gap-3">
        <span className={cn("grid size-11 shrink-0 place-items-center rounded-2xl", selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
          <Icon className="size-6" aria-hidden="true" />
        </span>
        <span className="font-heading text-lg leading-tight font-semibold">{title}</span>
      </span>
      <span className="text-muted-foreground">{text}</span>
      <ul className="flex flex-col gap-1.5 text-sm">
        {bullets.map((bullet) => (
          <li key={bullet} className="flex items-start gap-2">
            <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary-text" aria-hidden="true" />
            {bullet}
          </li>
        ))}
      </ul>
      <span className="mt-auto flex items-center gap-1.5 pt-1 font-mono text-xs font-bold text-muted-foreground">
        <ClockIcon className="size-3.5" aria-hidden="true" /> {time}
      </span>
    </label>
  );
}

function TwoOptions({ lessonId, onChosen }: { lessonId: string; onChosen: () => void }) {
  const [picked, setPicked] = useState<MasteryPick>(MasteryOptions.DEFAULT);
  const [busy, setBusy] = useState(false);

  const choose = async () => {
    setBusy(true);
    try {
      await lessonsApi.choose(lessonId, picked);
      onChosen();
    } catch (err) {
      toast.error(MasteryOptions.errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <>
      <fieldset className="flex flex-col gap-3" disabled={busy}>
        <legend className="mb-3 font-heading text-xl font-semibold">What would you like next?</legend>
        <div className="grid gap-4 md:grid-cols-2">
          {MasteryOptions.all().map((option) => (
            <ChoiceCard
              key={option.pick}
              name="mastery"
              value={option.pick}
              selected={picked === option.pick}
              onSelect={() => setPicked(option.pick)}
              icon={PICK_ICONS[option.pick]}
              {...option}
            />
          ))}
        </div>
      </fieldset>
      <Button size="lg" className="h-10 self-start px-4 text-base" onClick={choose} disabled={busy}>
        {MasteryOptions.buttonLabel(picked, busy)}
      </Button>
    </>
  );
}

/** The three sheets a lesson that was already waiting when the Expert lesson arrived was offered. */
function ThreeSheets({ lessonId, onChosen }: { lessonId: string; onChosen: () => void }) {
  const [picked, setPicked] = useState<MaterialKind>("revision_sheet");
  const [busy, setBusy] = useState(false);

  const choose = async () => {
    setBusy(true);
    try {
      await lessonsApi.choose(lessonId, { kind: picked });
      onChosen();
    } catch (err) {
      toast.error(err instanceof ApiError ? MasteryOptions.errorMessage(err) : "Could not start that sheet.");
      setBusy(false);
    }
  };

  return (
    <>
      <fieldset className="flex flex-col gap-3" disabled={busy}>
        <legend className="mb-3 font-heading text-xl font-semibold">What would help you most?</legend>
        <div className="grid gap-4 md:grid-cols-3">
          {SheetCatalog.all().map((sheet) => (
            <ChoiceCard
              key={sheet.kind}
              name="sheet"
              value={sheet.kind}
              selected={picked === sheet.kind}
              onSelect={() => setPicked(sheet.kind)}
              icon={SHEET_ICONS[sheet.kind]}
              title={sheet.title}
              text={sheet.text}
              bullets={sheet.bullets}
              time={sheet.time}
            />
          ))}
        </div>
      </fieldset>
      <div className="flex flex-col items-start gap-1.5">
        <Button size="lg" className="h-10 px-4 text-base" onClick={choose} disabled={busy}>
          {busy ? "Starting…" : SheetCatalog.makeLabel(picked)}
        </Button>
        <p className="text-sm text-muted-foreground">You can add the other sheets afterwards.</p>
      </div>
    </>
  );
}
