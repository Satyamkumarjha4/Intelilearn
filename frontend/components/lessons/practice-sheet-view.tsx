"use client";

import { EyeIcon } from "lucide-react";
import { useMemo, useReducer, useState } from "react";
import { toast } from "sonner";

import { QuestionInputField } from "@/components/lessons/question-input";
import { MutedBox, SheetHeading } from "@/components/lessons/sheet-parts";
import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { PracticeSession } from "@/lib/practice-session";
import { type AnswerValue } from "@/lib/question-inputs";
import { QuestionSolution } from "@/lib/question-solution";
import type { PracticeQuestion, PracticeSheet, Solution } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  lessonId: string;
  sheet: PracticeSheet;
  onSolutions?: (solutions: Record<string, Solution>) => void;
};

function SolutionView({ question, solution }: { question: PracticeQuestion; solution: Solution }) {
  const options = QuestionSolution.correctOptions(solution);
  return (
    <MutedBox className="bg-primary-soft text-sm">
      <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">
        Solution
      </p>
      {options && question.options && (
        <ul className="list-none font-bold">
          {options.map((index) => (
            <li key={index}>{question.options?.[index]}</li>
          ))}
        </ul>
      )}
      {solution.answer !== undefined && (
        <p className="font-bold">
          {solution.answer}
          {solution.unit ? ` ${solution.unit}` : ""}
        </p>
      )}
      {solution.model_answer && <Markdown>{solution.model_answer}</Markdown>}
      {solution.criteria && (
        <ul className="list-disc pl-5">
          {solution.criteria.map((criterion) => (
            <li key={criterion.text}>
              {criterion.text} <span className="font-mono text-xs text-muted-foreground">({QuestionSolution.marks(criterion.marks)})</span>
            </li>
          ))}
        </ul>
      )}
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

  const set = (id: string, value: AnswerValue | null) => {
    session.setAnswer(id, value ?? "");
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
        const correct = shown && solution ? QuestionSolution.correctOptions(solution) : undefined;
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

              <QuestionInputField
                question={question}
                answer={picked}
                label={`Answer to question ${index + 1}`}
                correct={correct}
                onAnswer={(value) => set(question.id, value)}
              />

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
