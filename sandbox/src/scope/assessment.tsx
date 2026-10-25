import React, { useState } from "react";

import { Markdown } from "./markdown";
import { post } from "./host";

type Question = {
  id: string; type: string; concept: string; difficulty: string; marks: number; question: string;
  options?: string[]; unit?: string; language?: string; starter_code?: string;
};
type Test = { title: string; questions: Question[] };

/**
 * The page-4 test. It collects answers and sends them to the page that embeds the lesson (`test_submit`); it never
 * sees the correct answers, and grading happens on the server.
 */
export function Assessment({ test }: { test: Test }) {
  const [answers, setAnswers] = useState<Record<string, number | string>>({});
  const [submitted, setSubmitted] = useState(false);
  const set = (id: string, value: number | string) => setAnswers((a) => ({ ...a, [id]: value }));
  const answered = Object.keys(answers).filter((id) => String(answers[id]).trim() !== "").length;

  return (
    <div className="flex flex-col gap-4" data-assessment>
      {test.questions.map((q, index) => (
        <div key={q.id} className="rounded-lg border p-4">
          <p className="mb-2 flex items-start justify-between gap-3 font-medium">
            <span className="flex gap-2">
              <span>{index + 1}.</span>
              <Markdown>{q.question}</Markdown>
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {q.difficulty} · {q.marks} marks
            </span>
          </p>
          {q.type === "mcq" && (
            <div role="radiogroup" aria-label={`Answer to question ${index + 1}`} className="flex flex-col gap-2">
              {q.options?.map((option, i) => (
                <button
                  key={i}
                  type="button"
                  role="radio"
                  aria-checked={answers[q.id] === i}
                  onClick={() => set(q.id, i)}
                  className={"rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted " + (answers[q.id] === i ? "border-primary bg-primary/5" : "")}
                >
                  {option}
                </button>
              ))}
            </div>
          )}
          {q.type === "numerical" && (
            <div className="flex items-center gap-2">
              <input
                aria-label={`Answer to question ${index + 1}`}
                inputMode="decimal"
                className="h-9 w-40 rounded-lg border bg-background px-2"
                value={String(answers[q.id] ?? "")}
                onChange={(e) => set(q.id, e.target.value)}
              />
              {q.unit && <span className="text-sm text-muted-foreground">{q.unit}</span>}
            </div>
          )}
          {["short_answer", "long_answer", "code"].includes(q.type) && (
            <textarea
              aria-label={`Answer to question ${index + 1}`}
              rows={q.type === "short_answer" ? 2 : 6}
              defaultValue={q.starter_code}
              className={"w-full rounded-lg border bg-background p-2 " + (q.type === "code" ? "font-mono text-sm" : "")}
              onChange={(e) => set(q.id, e.target.value)}
            />
          )}
        </div>
      ))}
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={answered === 0 || submitted}
          className="inline-flex h-9 items-center rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
          onClick={() => {
            post({ type: "test_submit", answers });
            setSubmitted(true);
          }}
        >
          Submit answers
        </button>
        <span className="text-sm text-muted-foreground">
          {submitted ? "Submitted. Your results appear next to the lesson." : `${answered} of ${test.questions.length} answered`}
        </span>
        {submitted && (
          <button type="button" className="text-sm underline" onClick={() => setSubmitted(false)}>
            Answer again
          </button>
        )}
      </div>
    </div>
  );
}
