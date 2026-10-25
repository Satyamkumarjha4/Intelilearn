"use client";

import { EyeIcon } from "lucide-react";
import { useMemo, useReducer, useState } from "react";
import { toast } from "sonner";

import { MutedBox, SheetHeading } from "@/components/lessons/sheet-parts";
import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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

const LETTERS = ["A", "B", "C", "D", "E", "F"];

function SolutionView({ question, solution }: { question: PracticeQuestion; solution: Solution }) {
  return (
    <MutedBox className="bg-primary-soft text-sm">
      <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">
        Solution
      </p>
      {solution.correct_index !== undefined && question.options && <p className="font-bold">{question.options[solution.correct_index]}</p>}
      {solution.answer !== undefined && (
        <p className="font-bold">
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
    </MutedBox>
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
      <SheetHeading eyebrow="Practice sheet" title={sheet.title}>
        <Markdown>{sheet.instructions}</Markdown>
      </SheetHeading>

      {session.score && (
        <Card role="status" className="border-primary/40 bg-primary-soft">
          <CardContent className="flex flex-col gap-0.5">
            <p className="font-heading text-lg font-semibold">
              {session.score.awarded} of {session.score.available} marks on the questions we can mark
            </p>
            {session.score.open_marks > 0 && (
              <p className="text-sm text-muted-foreground">
                The other {session.score.open_marks} marks are for written answers: compare yours with the solution.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {sheet.questions.map((question, index) => {
        const grade = session.gradeOf(question.id);
        const solution = solutions[question.id];
        const shown = session.isRevealed(question.id) || grade !== undefined;
        const picked = session.answerOf(question.id);
        const correctIndex = shown ? solution?.correct_index : undefined;
        return (
          <Card key={question.id} className="break-inside-avoid">
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">Question {index + 1}</h3>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge variant="outline">{question.difficulty}</Badge>
                  <Badge variant="primary">
                    {question.marks} {question.marks === 1 ? "mark" : "marks"}
                  </Badge>
                </span>
              </div>
              <Markdown className="font-heading text-lg leading-snug font-medium">{question.question}</Markdown>

              {question.type === "mcq" && question.options && (
                <div role="radiogroup" aria-label={`Answer to question ${index + 1}`} className="flex flex-col gap-2">
                  {question.options.map((option, i) => (
                    <button
                      key={i}
                      type="button"
                      role="radio"
                      aria-checked={picked === i}
                      onClick={() => set(question.id, i)}
                      className={cn(
                        "flex items-center gap-3 rounded-xl border-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
                        picked === i ? "border-primary bg-primary-soft" : "border-border",
                        correctIndex === i && "border-success bg-success-soft",
                        correctIndex !== undefined && picked === i && picked !== correctIndex && "border-destructive bg-destructive-soft",
                      )}
                    >
                      <span
                        className={cn(
                          "grid size-6 shrink-0 place-items-center rounded-md font-mono text-xs font-bold",
                          picked === i ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                        )}
                      >
                        {LETTERS[i]}
                      </span>
                      {option}
                    </button>
                  ))}
                </div>
              )}
              {question.type === "numerical" && (
                <div className="flex items-center gap-2">
                  <Input
                    inputMode="decimal"
                    autoComplete="off"
                    aria-label={`Answer to question ${index + 1}`}
                    className="max-w-48"
                    value={String(picked ?? "")}
                    onChange={(e) => set(question.id, e.target.value)}
                  />
                  {question.unit && <span className="text-sm text-muted-foreground">{question.unit}</span>}
                </div>
              )}
              {question.type === "short_answer" && (
                <Input
                  autoComplete="off"
                  aria-label={`Answer to question ${index + 1}`}
                  value={String(picked ?? "")}
                  onChange={(e) => set(question.id, e.target.value)}
                />
              )}
              {(question.type === "long_answer" || question.type === "code") && (
                <Textarea
                  aria-label={`Answer to question ${index + 1}`}
                  rows={question.type === "code" ? 8 : 5}
                  spellCheck={question.type !== "code"}
                  className={question.type === "code" ? "font-mono text-sm" : undefined}
                  defaultValue={question.starter_code}
                  onChange={(e) => set(question.id, e.target.value)}
                />
              )}

              {grade && grade.correct !== null && (
                <p role="status" className={cn("text-sm font-extrabold", grade.correct ? "text-success-text" : "text-destructive-text")}>
                  {grade.correct ? `Correct: ${grade.awarded} marks` : "Not quite"}
                </p>
              )}
              {shown && solution ? (
                <SolutionView question={question} solution={solution} />
              ) : (
                <Button variant="outline" size="sm" className="self-start print:hidden" onClick={() => reveal(question.id)}>
                  <EyeIcon /> Reveal solution
                </Button>
              )}
            </CardContent>
          </Card>
        );
      })}

      <div className="flex flex-wrap gap-3 print:hidden">
        <Button size="lg" onClick={check} disabled={busy || session.answered === 0}>
          {busy ? "Checking…" : "Check my answers"}
        </Button>
        {(session.score || session.answered > 0) && (
          <Button
            size="lg"
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
