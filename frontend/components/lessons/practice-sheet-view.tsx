"use client";

import { useMemo, useReducer, useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { PracticeSession } from "@/lib/practice-session";
import type { PracticeQuestion, PracticeSheet, Solution } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  lessonId: string;
  sheet: PracticeSheet;
  onSolutions?: (solutions: Record<string, Solution>) => void;
};

function SolutionView({ question, solution }: { question: PracticeQuestion; solution: Solution }) {
  return (
    <div className="rounded-lg bg-muted/50 p-3 text-sm" aria-label="Solution">
      <p className="font-medium">Solution</p>
      {solution.correct_index !== undefined && question.options && <p>{question.options[solution.correct_index]}</p>}
      {solution.answer !== undefined && (
        <p>
          {solution.answer}
          {solution.unit ? ` ${solution.unit}` : ""}
        </p>
      )}
      {solution.model_answer && <Markdown>{solution.model_answer}</Markdown>}
      {solution.key_points && (
        <ul className="list-disc pl-5">
          {solution.key_points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      )}
      {solution.rubric && (
        <ul className="list-disc pl-5">
          {solution.rubric.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      )}
      {solution.reference_solution && <pre className="overflow-x-auto font-mono">{solution.reference_solution}</pre>}
    </div>
  );
}

/** The same kind of question UI as the lesson test: answer, reveal a solution when you want it, or check everything. */
export function PracticeSheetView({ lessonId, sheet, onSolutions }: Props) {
  const session = useMemo(() => new PracticeSession(sheet.questions), [sheet]);
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const [solutions, setSolutions] = useState<Record<string, Solution>>({});
  const [busy, setBusy] = useState(false);

  const remember = (found: Record<string, Solution>) => {
    setSolutions((current) => ({ ...current, ...found }));
    onSolutions?.(found);
  };

  const reveal = async (id: string) => {
    try {
      const { solutions: found } = await lessonsApi.material(lessonId, "practice_sheet", [id]);
      session.reveal(id);
      remember(found);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not load the solution.");
    }
  };

  const check = async () => {
    setBusy(true);
    try {
      const grade = await lessonsApi.gradePractice(lessonId, session.payload());
      session.mark(grade);
      remember(Object.fromEntries(grade.results.map((r) => [r.id, r.solution])));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not check your answers.");
    } finally {
      setBusy(false);
      rerender();
    }
  };

  const set = (id: string, value: number | string) => {
    session.setAnswer(id, value);
    rerender();
  };

  return (
    <article className="flex flex-col gap-4">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{sheet.title}</h2>
        <Markdown className="text-muted-foreground">{sheet.instructions}</Markdown>
      </header>

      {session.score && (
        <Card role="status">
          <CardHeader>
            <CardTitle>
              {session.score.awarded} of {session.score.available} marks on the questions we can mark
            </CardTitle>
            {session.score.open_marks > 0 && (
              <p className="text-sm text-muted-foreground">
                The other {session.score.open_marks} marks are for written answers: compare yours with the solution.
              </p>
            )}
          </CardHeader>
        </Card>
      )}

      {sheet.questions.map((question, index) => {
        const grade = session.gradeOf(question.id);
        const solution = solutions[question.id];
        const shown = session.isRevealed(question.id) || grade !== undefined;
        return (
          <Card key={question.id} className="break-inside-avoid">
            <CardHeader>
              <CardTitle className="flex items-start justify-between gap-3 text-base">
                <span className="flex gap-2">
                  <span>{index + 1}.</span>
                  <Markdown>{question.question}</Markdown>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge variant="outline">{question.difficulty}</Badge>
                  <Badge variant="secondary">{question.marks} marks</Badge>
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {question.type === "mcq" && question.options && (
                <div role="radiogroup" aria-label={`Answer to question ${index + 1}`} className="flex flex-col gap-2">
                  {question.options.map((option, i) => (
                    <button
                      key={i}
                      type="button"
                      role="radio"
                      aria-checked={session.answerOf(question.id) === i}
                      onClick={() => set(question.id, i)}
                      className={cn(
                        "rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                        session.answerOf(question.id) === i && "border-primary bg-primary/5 ring-1 ring-primary",
                      )}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              )}
              {question.type === "numerical" && (
                <div className="flex items-center gap-2">
                  <Input
                    inputMode="decimal"
                    aria-label={`Answer to question ${index + 1}`}
                    className="max-w-40"
                    value={String(session.answerOf(question.id) ?? "")}
                    onChange={(e) => set(question.id, e.target.value)}
                  />
                  {question.unit && <span className="text-sm text-muted-foreground">{question.unit}</span>}
                </div>
              )}
              {(question.type === "short_answer" || question.type === "long_answer" || question.type === "code") && (
                <Textarea
                  aria-label={`Answer to question ${index + 1}`}
                  rows={question.type === "short_answer" ? 2 : 5}
                  className={question.type === "code" ? "font-mono" : undefined}
                  defaultValue={question.starter_code}
                  onChange={(e) => set(question.id, e.target.value)}
                />
              )}

              {grade && grade.correct !== null && (
                <p role="status" className={grade.correct ? "text-sm text-emerald-700 dark:text-emerald-400" : "text-sm text-destructive"}>
                  {grade.correct ? `Correct: ${grade.awarded} marks` : "Not quite"}
                </p>
              )}
              {shown && solution ? (
                <SolutionView question={question} solution={solution} />
              ) : (
                <Button variant="ghost" size="sm" className="self-start print:hidden" onClick={() => reveal(question.id)}>
                  Reveal solution
                </Button>
              )}
            </CardContent>
          </Card>
        );
      })}

      <div className="flex gap-2 print:hidden">
        <Button onClick={check} disabled={busy || session.answered === 0}>
          {busy ? "Checking…" : "Check my answers"}
        </Button>
        {(session.score || session.answered > 0) && (
          <Button
            variant="outline"
            onClick={() => {
              session.reset();
              setSolutions({});
              rerender();
            }}
          >
            Start again
          </Button>
        )}
      </div>
    </article>
  );
}
