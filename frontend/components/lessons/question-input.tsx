"use client";

import { CheckIcon } from "lucide-react";
import type { ComponentType } from "react";

import { CodeEditorLoader } from "@/components/lessons/code-editor-loader";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { CodeLanguages } from "@/lib/code-languages";
import { type AnswerValue, type InputQuestion, QuestionInputs, type Widget } from "@/lib/question-inputs";
import { cn } from "@/lib/utils";

const LETTERS = ["A", "B", "C", "D", "E", "F"];

export type QuestionInputProps = {
  question: InputQuestion;
  answer: AnswerValue | undefined;
  /** What the field is called for a screen reader, for example "Your answer" or "Answer to question 3". */
  label: string;
  disabled?: boolean;
  /** Once the solution is shown: the options that are right, so the picked ones can be marked. */
  correct?: number[];
  onAnswer: (value: AnswerValue | null) => void;
};

function optionClasses(picked: boolean, shown: boolean | undefined, right: boolean) {
  return cn(
    "flex items-center gap-3 rounded-xl border-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
    picked ? "border-primary bg-primary-soft" : "border-border",
    shown && right && "border-success bg-success-soft",
    shown && picked && !right && "border-destructive bg-destructive-soft",
  );
}

function Letter({ index, on, square }: { index: number; on: boolean; square?: boolean }) {
  return (
    <span className={cn("grid size-6 shrink-0 place-items-center font-mono text-xs font-bold", square ? "rounded-md" : "rounded-full", on ? "bg-primary-action text-primary-foreground" : "bg-muted text-muted-foreground")}>
      {on && square ? <CheckIcon className="size-3.5" aria-hidden="true" /> : LETTERS[index]}
    </span>
  );
}

function Choice({ question, answer, label, disabled, correct, onAnswer }: QuestionInputProps) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-col gap-2">
      {(question.options ?? []).map((option, index) => (
        <button
          key={index}
          type="button"
          role="radio"
          data-deck-option
          aria-checked={answer === index}
          disabled={disabled}
          onClick={() => onAnswer(index)}
          className={optionClasses(answer === index, correct !== undefined, correct?.includes(index) ?? false)}
        >
          <Letter index={index} on={answer === index} />
          {option}
        </button>
      ))}
    </div>
  );
}

function Multi({ question, answer, label, disabled, correct, onAnswer }: QuestionInputProps) {
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-2">
      {(question.options ?? []).map((option, index) => {
        const picked = QuestionInputs.msq.isPicked(answer, index);
        return (
          <button
            key={index}
            type="button"
            role="checkbox"
            data-deck-option
            aria-checked={picked}
            disabled={disabled}
            onClick={() => onAnswer(QuestionInputs.msq.toggle(answer, index))}
            className={optionClasses(picked, correct !== undefined, correct?.includes(index) ?? false)}
          >
            <Letter index={index} on={picked} square />
            {option}
          </button>
        );
      })}
    </div>
  );
}

function NumberBox({ question, answer, label, disabled, onAnswer }: QuestionInputProps) {
  return (
    <div className="flex items-center gap-2">
      <Input
        aria-label={label}
        inputMode={QuestionInputs.number.inputMode(question)}
        autoComplete="off"
        disabled={disabled}
        value={typeof answer === "string" ? answer : ""}
        onChange={(e) => onAnswer(e.target.value)}
        className="max-w-48"
      />
      {question.unit && <span className="text-sm text-muted-foreground">{question.unit}</span>}
    </div>
  );
}

function TextBox({ answer, label, disabled, onAnswer }: QuestionInputProps) {
  return <Input aria-label={label} autoComplete="off" disabled={disabled} value={typeof answer === "string" ? answer : ""} onChange={(e) => onAnswer(e.target.value)} />;
}

function Paragraph({ answer, label, disabled, onAnswer }: QuestionInputProps) {
  return <Textarea aria-label={label} rows={6} disabled={disabled} value={typeof answer === "string" ? answer : ""} onChange={(e) => onAnswer(e.target.value)} />;
}

function Code({ question, answer, label, disabled, onAnswer }: QuestionInputProps) {
  return (
    <CodeEditorLoader
      label={question.language ? `${label} (${CodeLanguages.label(question.language)})` : label}
      language={question.language}
      disabled={disabled}
      value={QuestionInputs.code.text(question, answer)}
      onChange={(text) => onAnswer(QuestionInputs.code.isStarter(question, text) ? null : text)}
    />
  );
}

/** The widget of each kind of input (`QuestionInputs`). A new widget is an entry here. */
const WIDGETS: Record<Widget, ComponentType<QuestionInputProps>> = {
  choice: Choice,
  multi: Multi,
  number: NumberBox,
  text: TextBox,
  paragraph: Paragraph,
  code: Code,
};

/** Where a learner answers a question, whatever its kind; the test screen and the practice sheet both use it. */
export function QuestionInputField(props: QuestionInputProps) {
  const input = QuestionInputs.forQuestion(props.question);
  const Widget = WIDGETS[input.widget];
  const hint = input.instruction(props.question);
  return (
    <>
      {hint && <p className="text-sm font-semibold text-muted-foreground">{hint}</p>}
      <Widget {...props} />
    </>
  );
}
