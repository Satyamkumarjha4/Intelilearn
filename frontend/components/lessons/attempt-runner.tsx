"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { FlashcardDeck } from "@/components/lessons/flashcard-deck";
import { QuestionInputField } from "@/components/lessons/question-input";
import { useAttemptDeck } from "@/components/lessons/use-attempt-deck";
import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card as Panel, CardContent } from "@/components/ui/card";
import { AnswerLocker, AttemptErrors, AttemptSubmitFlow } from "@/lib/attempt-flow";
import type { DeckAnswer } from "@/lib/deck-session";
import { lessonsApi } from "@/lib/lessons-api";
import { QuestionInputs } from "@/lib/question-inputs";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import type { LearnerTest, LearnerTestQuestion, TestSubmission } from "@/lib/types";

type Props = {
  lessonId: string;
  /** The open attempt: its questions and the answers the server already holds. */
  test: LearnerTest;
  /** The attempt was handed in (or turned out to be over already): the attempt as it ended. */
  onSubmitted: (attempt: TestSubmission) => void;
  /** An attempt changed: the lesson (its Test tab badge, its journey) should be read again. */
  onChanged: () => void;
};

/**
 * One attempt at the test: one card per question, forward only. Moving on saves the answer on the server and locks the
 * card there, so a refresh resumes on the same card and another tab cannot go back either. The last card asks for a
 * yes, then the attempt is handed in; a lesson attempt is marked straight away, and an older lesson's written answers
 * are followed to the end of their marking.
 */
export function AttemptRunner({ lessonId, test, onSubmitted, onChanged }: Props) {
  const attemptId = test.attempt!.id;
  const ids = test.questions.map((q) => q.id);
  const { deck, answer, advance } = useAttemptDeck(ids, test.answers);
  const locker = useRef(new AnswerLocker(lessonsApi));
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  // A refresh after the last card leaves a finished deck whose hand-in never went through.
  const [phase, setPhase] = useState<"taking" | "marking" | "failed">(deck.finished ? "failed" : "taking");
  const last = useRef<Record<string, DeckAnswer>>({});
  const flow = useRef<AttemptSubmitFlow | null>(null);
  useEffect(() => () => flow.current?.dispose(), []);
  const byId = new Map(test.questions.map((q) => [q.id, q]));

  const handIn = async () => {
    setPhase("marking");
    const run = new AttemptSubmitFlow(lessonsApi, (runId, onEnd) => {
      const events = new RunEventStream(runId, (event) => TERMINAL_EVENTS.has(event.name) && onEnd());
      return () => events.close();
    });
    flow.current = run;
    try {
      const done = await run.run(lessonId, attemptId, last.current, () => onChanged());
      onChanged();
      onSubmitted(done);
    } catch (err) {
      toast.error(AttemptErrors.message(err, "Could not hand in your test."));
      setPhase("failed");
    }
  };

  const onContinue = async () => {
    if (saving) return;
    if (deck.isLast) {
      setConfirming(true);
      return;
    }
    const id = deck.current;
    const value = id === undefined ? undefined : deck.answerOf(id);
    if (id === undefined || value === undefined) return;
    setSaving(true);
    const saved = await locker.current.lock(lessonId, attemptId, id, value);
    setSaving(false);
    if (saved.ok) {
      advance();
      return;
    }
    toast.error(saved.message);
    if (saved.sealed) onChanged();
  };

  if (phase === "marking") {
    return (
      <Panel>
        <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
          <Loader2Icon className="size-10 text-primary motion-safe:animate-spin" aria-hidden="true" />
          <h2 className="font-heading text-2xl font-semibold">Marking your test</h2>
          <p className="text-muted-foreground" aria-live="polite">
            Your answers are in. You can leave this page; your result will be here.
          </p>
        </CardContent>
      </Panel>
    );
  }
  if (deck.finished) {
    return (
      <Panel>
        <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
          <h2 className="font-heading text-2xl font-semibold">We couldn&apos;t hand in your test</h2>
          <p className="text-muted-foreground">Your answers are saved, so nothing is lost. Try again.</p>
          <Button variant="marigold" onClick={handIn}>
            Hand in my test
          </Button>
        </CardContent>
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-2xl font-semibold tracking-tight">
          Test <span className="font-normal text-muted-foreground">· Show what you learned</span>
        </h2>
        <Badge variant="marigold">Attempt {test.attempt!.attempt_no}</Badge>
      </div>
      <FlashcardDeck
        label="Test questions"
        session={deck}
        lockHint="Your answer locks when you continue"
        continueLabel="Continue"
        finishLabel="Finish and hand in"
        finishVariant="marigold"
        busy={saving}
        onContinue={() => void onContinue()}
        onKey={(key, id) => {
          const question = byId.get(id);
          if (!question) return;
          const next = QuestionInputs.of(question.type).onKey(question, deck.answerOf(id), key);
          if (next !== undefined) answer(next);
        }}
        renderCard={(id, locked) => (
          <QuestionCard question={byId.get(id)!} answer={deck.answerOf(id)} locked={locked} onAnswer={answer} />
        )}
      />
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Hand in your test?"
        description="You'll see your score straight away. You can't change your answers after this, but you can try again later with new questions."
        confirmLabel="Hand it in"
        cancelLabel="Not yet"
        confirmVariant="default"
        onConfirm={() => {
          const id = deck.current;
          const value = id === undefined ? undefined : deck.answerOf(id);
          last.current = id !== undefined && value !== undefined ? { [id]: value } : {};
          advance();
          void handIn();
        }}
      />
    </div>
  );
}

function QuestionCard({ question, answer, locked, onAnswer }: {
  question: LearnerTestQuestion;
  answer: DeckAnswer | undefined;
  locked: boolean;
  onAnswer: (value: DeckAnswer | null) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2 text-xs font-bold text-muted-foreground">
        <span>{QuestionInputs.of(question.type).label}</span>
        <span className="font-mono">
          {question.marks} {question.marks === 1 ? "mark" : "marks"}
        </span>
      </div>
      <Markdown className="font-heading text-lg leading-snug font-medium">{question.question}</Markdown>
      <QuestionInputField question={question} answer={answer} label={QuestionInputs.of(question.type).answerLabel} disabled={locked} onAnswer={onAnswer} />
    </div>
  );
}
