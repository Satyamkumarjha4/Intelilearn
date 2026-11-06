"use client";

import { CheckIcon, ClockIcon, GraduationCapIcon, ScrollTextIcon, TrophyIcon, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { CostLabel } from "@/components/credits/cost-label";
import { QuizReview } from "@/components/lessons/quiz-review";
import { Button } from "@/components/ui/button";
import { CostSizes } from "@/lib/credits/cost-sizes";
import { lessonsApi } from "@/lib/lessons-api";
import { MasteryOptions } from "@/lib/mastery-options";
import { MasteryBanner } from "@/lib/study-sheets";
import type { LessonDetail, MasteryPick } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { lesson: Pick<LessonDetail, "id" | "results">; onChosen: () => void };

const PICK_ICONS: Record<MasteryPick, LucideIcon> = { lesson: GraduationCapIcon, sheets: ScrollTextIcon };

/** The learner knew (nearly) everything: celebrate it, then let them choose what happens next. The button follows the
 *  card picked. */
export function MasteryChoice({ lesson, onChosen }: Props) {
  const result = lesson.results.diagnostic;
  const banner = MasteryBanner.of(result);

  return (
    <section aria-label="What next?" className="flex flex-col gap-6">
      <div className="flex items-center gap-4 rounded-[22px] border-[1.5px] border-marigold/60 bg-marigold-soft px-5 py-4">
        <span className="grid size-14 shrink-0 place-items-center rounded-full bg-marigold text-marigold-foreground shadow-[0_3px_0_var(--marigold-deep)]">
          <TrophyIcon className="size-7" aria-hidden="true" />
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="font-heading text-2xl font-semibold tracking-tight">{banner.headline}</h2>
          <p className="text-marigold-text">{banner.text}</p>
        </div>
      </div>

      <TwoOptions lessonId={lesson.id} onChosen={onChosen} />

      {result && <QuizReview lessonId={lesson.id} kind="diagnostic" />}
    </section>
  );
}

type CardProps = { name: string; value: string; selected: boolean; onSelect: () => void; icon: LucideIcon; title: string; text: string; bullets: string[]; time: string; cost?: React.ReactNode };

/** One card of a choice: a radio button that looks like a card, picked with the mouse or the keyboard. */
function ChoiceCard({ name, value, selected, onSelect, icon: Icon, title, text, bullets, time, cost }: CardProps) {
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
      {cost}
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
              cost={<CostLabel ask={CostSizes.mastery(option.pick)} halfBack={option.pick === "sheets"} />}
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
