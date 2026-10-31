"use client";

import { CheckCircle2Icon, ChevronDownIcon, CircleDashedIcon, MinusCircleIcon, XCircleIcon } from "lucide-react";

import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { QuestionInputs } from "@/lib/question-inputs";
import { TestResultView } from "@/lib/test-session";
import { type AnswerText, type Status, TestReport } from "@/lib/test-report";
import type { LearnerTestQuestion, QuestionResult, ScoreCard } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The score of an attempt: a ring with the percent, how many questions went which way, and what changed since the last try. */
export function ScoreHero({ card, changes }: { card: ScoreCard; changes: string[] }) {
  const { percent, awarded, available } = card.score;
  const stats = TestReport.stats(card.questions);
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-5 px-6 py-6 sm:flex-row sm:gap-8">
        <div className="relative size-36 shrink-0" role="img" aria-label={`${percent} percent: ${awarded} of ${available} marks`}>
          <svg viewBox="0 0 128 128" className="size-full -rotate-90">
            <circle cx="64" cy="64" r={radius} fill="none" strokeWidth="12" className="stroke-success-soft" />
            <circle
              cx="64" cy="64" r={radius} fill="none" strokeWidth="12" strokeLinecap="round"
              className="stroke-success motion-safe:transition-[stroke-dashoffset]"
              strokeDasharray={circumference}
              strokeDashoffset={circumference * (1 - Math.min(Math.max(percent, 0), 100) / 100)}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-heading text-3xl font-semibold tabular-nums">{percent}%</span>
            <span className="text-xs text-muted-foreground">
              {awarded} of {available} marks
            </span>
          </div>
        </div>
        <div className="flex flex-col items-center gap-3 text-center sm:items-start sm:text-left">
          <h2 className="font-heading text-2xl font-semibold tracking-tight">{TestReport.headline(percent)}</h2>
          {changes.length > 0 && <p className="text-sm font-semibold text-muted-foreground">{changes.join(" · ")}</p>}
          <ul className="flex flex-wrap justify-center gap-2 sm:justify-start">
            <li><Badge variant="success">{stats.correct} correct</Badge></li>
            {stats.partial > 0 && <li><Badge variant="marigold">{stats.partial} partly right</Badge></li>}
            <li><Badge variant="destructive-soft">{stats.missed} missed</Badge></li>
            {stats.aiGraded > 0 && (
              <li><Badge variant="insight">{stats.aiGraded} written {stats.aiGraded === 1 ? "answer" : "answers"} graded by AI</Badge></li>
            )}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

/** Every question of an attempt with the learner's answer, the right one, what it was marked on and the feedback. */
const ICON: Record<Status, React.ReactNode> = {
  right: <CheckCircle2Icon className="size-5 text-success" aria-label="Right" />,
  partial: <MinusCircleIcon className="size-5 text-marigold-deep" aria-label="Partly right" />,
  wrong: <XCircleIcon className="size-5 text-destructive" aria-label="Missed" />,
  pending: <CircleDashedIcon className="size-5 text-muted-foreground" aria-label="Being marked" />,
};

export function QuestionBreakdown({ rows, questions, answers }: { rows: QuestionResult[]; questions: LearnerTestQuestion[]; answers: Record<string, unknown> }) {
  const byId = new Map(questions.map((q) => [q.id, q]));
  return (
    <section aria-labelledby="questions-heading" className="flex flex-col gap-3">
      <h2 id="questions-heading" className="font-heading text-xl font-semibold">Question by question</h2>
      <ol className="flex flex-col gap-2">
        {rows.map((row, index) => {
          const question = byId.get(row.id);
          const status = TestReport.status(row);
          const yours = question ? TestReport.yourAnswer(question, answers[row.id]) : null;
          const correct = question && status !== "right" ? TestReport.correctAnswer(question, row.solution) : null;
          return (
            <li key={row.id}>
              <details className="group rounded-2xl border-[1.5px] border-border bg-card open:shadow-card">
                <summary className="flex cursor-pointer list-none items-center gap-3 rounded-2xl px-4 py-3 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
                  {ICON[status]}
                  <span className="min-w-0 flex-1">
                    <span className="mr-2 font-mono text-xs text-muted-foreground">{index + 1}</span>
                    <span className="line-clamp-2 font-semibold">{question?.question ?? row.concept}</span>
                  </span>
                  {row.type !== "mcq" && <Badge variant="secondary" className="hidden sm:inline-flex">{QuestionInputs.of(row.type).label}</Badge>}
                  <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">{TestResultView.label(row)}</span>
                  <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground motion-safe:transition-transform group-open:rotate-180" aria-hidden="true" />
                </summary>
                <div className="flex flex-col gap-3 border-t border-dashed border-border px-4 py-3 text-sm">
                  {question && <Markdown className="text-base">{question.question}</Markdown>}
                  <Answer label="Your answer" answer={yours} empty="You didn't answer this one." />
                  {correct && <Answer label={question?.type === "msq" ? "Correct answers" : "Correct answer"} answer={correct} />}
                  {TestReport.criteria(row).length > 0 && (
                    <div className="flex flex-col gap-1">
                      <p className="text-xs font-extrabold text-muted-foreground">What it was marked on</p>
                      <ul className="flex flex-col gap-1">
                        {TestReport.criteria(row).map((criterion) => (
                          <li key={criterion.text} className="flex items-start justify-between gap-3">
                            <span>{criterion.text}</span>
                            <span className={cn("font-mono text-xs whitespace-nowrap", criterion.full ? "text-success-text" : "text-muted-foreground")}>{criterion.earned}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {row.feedback && (
                    <div className="flex flex-col gap-1 rounded-xl bg-insight-soft px-3 py-2.5">
                      <p className="text-xs font-extrabold text-insight-text">Feedback{TestResultView.source(row) === "Graded by AI" ? " · graded by AI" : ""}</p>
                      <p>{row.feedback}</p>
                    </div>
                  )}
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Answer({ label, answer, empty }: { label: string; answer: AnswerText | null; empty?: string }) {
  if (!answer && !empty) return null;
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-extrabold text-muted-foreground">{label}</p>
      {answer ? (
        <p className={cn("whitespace-pre-wrap", answer.code && "overflow-x-auto rounded-lg bg-muted p-2 font-mono text-xs")}>{answer.text}</p>
      ) : (
        <p className="text-muted-foreground italic">{empty}</p>
      )}
    </div>
  );
}
