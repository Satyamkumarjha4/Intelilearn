"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { OnboardingFlow } from "@/lib/onboarding-flow";
import { cn } from "@/lib/utils";

type Props = {
  level: string;
  grade: string;
  field: string;
  onGrade: (value: string) => void;
  onField: (value: string) => void;
  errors?: { grade?: string; field?: string };
};

/** The question that follows the study level: a class or year as chips, and/or what they study or work in. */
export function StudyFollowUp({ level, grade, field, onGrade, onField, errors }: Props) {
  const ask = OnboardingFlow.followUp(level);
  if (!ask.gradeQuestion && !ask.fieldQuestion) return null;
  return (
    <div className="flex flex-col gap-4 rounded-2xl border-[1.5px] border-dashed border-primary/50 bg-primary-soft/40 p-4">
      {ask.gradeQuestion && (
        <div className="flex flex-col gap-2">
          <p id="grade-question" className="font-extrabold">{ask.gradeQuestion}</p>
          <div role="radiogroup" aria-labelledby="grade-question" className="flex flex-wrap gap-2">
            {ask.grades.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={grade === option}
                onClick={() => onGrade(option)}
                className={cn(
                  "rounded-full border-2 px-3.5 py-1 text-sm font-extrabold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  grade === option ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted",
                )}
              >
                {option}
              </button>
            ))}
          </div>
          {errors?.grade && <p className="text-sm text-destructive">{errors.grade}</p>}
        </div>
      )}
      {ask.fieldQuestion && (
        <div className="flex flex-col gap-2">
          <Label htmlFor="field_of_study" className="font-extrabold">
            {ask.fieldQuestion}
          </Label>
          <Input id="field_of_study" value={field} maxLength={150} autoComplete="off" onChange={(e) => onField(e.target.value)} className="bg-card" />
          {errors?.field && <p className="text-sm text-destructive">{errors.field}</p>}
        </div>
      )}
    </div>
  );
}
