import React from "react";

import { CodeBlock } from "./code";
import { BlockMath, Markdown } from "./markdown";


type Section = {
  id: string;
  heading: string;
  body: string;
  key_points?: string[];
  worked_examples?: { problem: string; solution: string }[];
  formulas?: { latex: string; explanation: string }[];
  code_snippets?: { language: string; code: string; explanation: string }[];
  callouts?: { kind: string; text: string }[];
};

export function PageFrame({ title, subtitle, children }: { title?: string; subtitle?: string; children?: React.ReactNode }) {
  return (
    <article data-lesson-page className="flex flex-col gap-6">
      <header>
        {title && <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>}
        {subtitle && <p className="mt-1 text-muted-foreground">{subtitle}</p>}
      </header>
      {children}
    </article>
  );
}

const CALLOUTS: Record<string, string> = {
  note: "border-primary/40 bg-primary-soft",
  tip: "border-success/40 bg-success-soft",
  warning: "border-marigold/40 bg-marigold-soft",
  example: "border-insight/40 bg-insight-soft",
};

export function Callout({ kind = "note", children }: { kind?: string; children?: React.ReactNode }) {
  return (
    <aside className={"rounded-lg border-l-4 p-3 text-sm " + (CALLOUTS[kind] ?? CALLOUTS.note)}>
      <strong className="mr-1 capitalize">{kind}:</strong>
      {typeof children === "string" ? <Markdown>{children}</Markdown> : children}
    </aside>
  );
}

export function KeyPoints({ title = "Key points", points }: { title?: string; points?: string[] }) {
  if (!points?.length) return null;
  return (
    <div className="rounded-lg border p-4">
      <h3 className="mb-2 font-medium">{title}</h3>
      <ul className="list-disc pl-5">
        {points.map((point, i) => (
          <li key={i}>
            <Markdown>{point}</Markdown>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function WorkedExample({ example }: { example: { problem: string; solution: string } }) {
  return (
    <div className="rounded-lg bg-muted/60 p-4">
      <p className="mb-1 text-sm font-medium uppercase tracking-wide text-muted-foreground">Worked example</p>
      <Markdown>{example.problem}</Markdown>
      <div className="mt-2 border-t pt-2">
        <Markdown>{example.solution}</Markdown>
      </div>
    </div>
  );
}

export function FormulaCard({ formula }: { formula: { latex: string; explanation: string } }) {
  return (
    <div className="rounded-lg border p-4">
      <BlockMath>{formula.latex}</BlockMath>
      <Markdown>{formula.explanation}</Markdown>
    </div>
  );
}

/** A whole section: heading, body, formulas, examples, code, callouts, key points; then what the page put inside. */
export function Section({ section, children }: { section: Section; children?: React.ReactNode }) {
  return (
    <section id={section.id} className="flex flex-col gap-4">
      <h2 className="text-2xl font-semibold tracking-tight">{section.heading}</h2>
      <Markdown>{section.body}</Markdown>
      {section.formulas?.map((f, i) => <FormulaCard key={i} formula={f} />)}
      {section.worked_examples?.map((ex, i) => <WorkedExample key={i} example={ex} />)}
      {section.code_snippets?.map((c, i) => (
        <div key={i} className="flex flex-col gap-1">
          <CodeBlock code={c.code} language={c.language} />
          {c.explanation && <p className="text-sm text-muted-foreground">{c.explanation}</p>}
        </div>
      ))}
      {section.callouts?.map((c, i) => <Callout key={i} kind={c.kind}>{c.text}</Callout>)}
      <KeyPoints points={section.key_points} />
      {children}
    </section>
  );
}

export function Button({ onClick, variant = "default", children, ...rest }: {
  onClick?: () => void; variant?: "default" | "outline"; children?: React.ReactNode; disabled?: boolean; "aria-label"?: string;
}) {
  const style = variant === "outline" ? "border bg-background hover:bg-muted" : "bg-primary text-primary-foreground hover:opacity-90";
  return (
    <button type="button" onClick={onClick} className={"inline-flex h-9 items-center rounded-lg px-3 text-sm font-medium disabled:opacity-50 " + style} {...rest}>
      {children}
    </button>
  );
}

export function Slider({ label, min = 0, max = 100, step = 1, value, onChange }: {
  label: string; min?: number; max?: number; step?: number; value: number; onChange: (n: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span>
        {label}: <strong>{value}</strong>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}
