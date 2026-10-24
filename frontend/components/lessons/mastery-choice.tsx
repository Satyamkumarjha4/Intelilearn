"use client";

import { BookTextIcon, ClipboardCheckIcon, FileTextIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import type { MaterialKind, QuizResultSummary } from "@/lib/types";

export const MATERIAL_OPTIONS: { kind: MaterialKind; title: string; text: string; icon: typeof FileTextIcon }[] = [
  { kind: "cheat_sheet", title: "Cheat sheet", text: "Formulas, key terms and rules on one or two pages.", icon: FileTextIcon },
  { kind: "revision_sheet", title: "Revision sheet", text: "Every subtopic with key points, examples and common mistakes.", icon: BookTextIcon },
  { kind: "practice_sheet", title: "Practice sheet", text: "15 to 25 questions, easy to hard, with solutions when you want them.", icon: ClipboardCheckIcon },
];

type Props = { lessonId: string; result: QuizResultSummary | null; onChosen: () => void };

/** The learner knew everything: offer the three sheets instead of a lesson. */
export function MasteryChoice({ lessonId, result, onChosen }: Props) {
  const [busy, setBusy] = useState<MaterialKind | null>(null);

  const choose = async (kind: MaterialKind) => {
    setBusy(kind);
    try {
      await lessonsApi.choose(lessonId, kind);
      onChosen();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start that sheet.");
      setBusy(null);
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">You already know this well</h1>
        <p className="text-muted-foreground">
          {result ? `${result.correct} of ${result.total} correct. ` : ""}Pick a study sheet to consolidate it; you can get the others later.
        </p>
      </header>
      <div className="grid gap-3 sm:grid-cols-3">
        {MATERIAL_OPTIONS.map(({ kind, title, text, icon: Icon }) => (
          <button
            key={kind}
            type="button"
            disabled={busy !== null}
            onClick={() => choose(kind)}
            className="rounded-xl text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
          >
            <Card className="h-full transition-colors hover:bg-muted/50">
              <CardHeader>
                <Icon className="mb-1 size-5 text-muted-foreground" />
                <CardTitle>{busy === kind ? "Starting…" : title}</CardTitle>
                <CardDescription>{text}</CardDescription>
              </CardHeader>
            </Card>
          </button>
        ))}
      </div>
    </section>
  );
}
