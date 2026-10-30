"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { FlashcardDeck } from "@/components/lessons/flashcard-deck";
import { QuestionInputField } from "@/components/lessons/question-input";
import { useDeck } from "@/components/lessons/use-deck";
import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card as Panel, CardContent } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import type { DeckAnswer } from "@/lib/deck-session";
import { lessonsApi } from "@/lib/lessons-api";
import { RunEventStream, TERMINAL_EVENTS } from "@/lib/run-events";
import { AlreadySubmitted, TestSubmitFlow } from "@/lib/test-session";
import { QuestionInputs } from "@/lib/question-inputs";
import type { LearnerTest, LearnerTestQuestion, TestSubmission } from "@/lib/types";

type Props = {
  lessonId: string;
  test: LearnerTest;
  /** The test has been submitted: the marked submission, or null when the server says it already was. */
  onSubmitted: (submission: TestSubmission | null) => void;
  /** The submission was created: the lesson (its Test tab badge, its journey) should be read again. */
  onChanged: () => void;
};

/** The final test: one card per question, forward only, one attempt. The last card asks for a final yes, then the
 *  answers are sent and the marking is followed to its end. */
export function TestRunner({ lessonId, test, onSubmitted, onChanged }: Props) {
  const ids = test.questions.map((q) => q.id);
  const { deck, answer, advance, clear } = useDeck(`${lessonId}:test`, ids);
  const [confirming, setConfirming] = useState(false);
  // A refresh after the last card leaves a finished deck whose answers never got sent.
  const [phase, setPhase] = useState<"taking" | "marking" | "failed">(deck.finished ? "failed" : "taking");
  const flow = useRef<TestSubmitFlow | null>(null);
  useEffect(() => () => flow.current?.dispose(), []);
  const byId = new Map(test.questions.map((q) => [q.id, q]));

  const send = async () => {
    setPhase("marking");
    const run = new TestSubmitFlow(lessonsApi, (runId, onEnd) => {
      const events = new RunEventStream(runId, (event) => TERMINAL_EVENTS.has(event.name) && onEnd());
      return () => events.close();
    });
    flow.current = run;
    try {
      const done = await run.run(lessonId, deck.payload(), onChanged);
      clear();
      onChanged();
      onSubmitted(done);
    } catch (err) {
      if (AlreadySubmitted.idOf(err)) {
        clear();
        onSubmitted(null);
        return;
      }
      toast.error(err instanceof ApiError ? err.message : "Could not send your test.");
      setPhase("failed");
    }
  };

  const onContinue = () => {
    if (deck.isLast) setConfirming(true);
    else advance();
  };

  if (phase === "marking") {
    return (
      <Panel>
        <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
          <Loader2Icon className="size-10 text-primary motion-safe:animate-spin" aria-hidden="true" />
          <h2 className="font-heading text-2xl font-semibold">Marking your test</h2>
          <p className="text-muted-foreground" aria-live="polite">
            Your answers are in and final. The written ones take a little longer to mark. You can leave this page; your result will be here.
          </p>
        </CardContent>
      </Panel>
    );
  }
  if (deck.finished) {
    return (
      <Panel>
        <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center">
          <h2 className="font-heading text-2xl font-semibold">We couldn&apos;t send your test</h2>
          <p className="text-muted-foreground">Your answers are saved on this page, so nothing is lost. Try again.</p>
          <Button variant="marigold" onClick={send}>
            Send my test
          </Button>
        </CardContent>
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-2xl font-semibold tracking-tight">
          Final test <span className="font-normal text-muted-foreground">· Show what you learned</span>
        </h2>
        <Badge variant="marigold">One attempt</Badge>
      </div>
      <FlashcardDeck
        label="Final test questions"
        session={deck}
        lockHint="Your answer locks when you continue"
        continueLabel="Continue"
        finishLabel="Finish and submit"
        finishVariant="marigold"
        onContinue={onContinue}
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
        title="Submit your test?"
        description="This is your only attempt. Once you submit, your answers and score are final and can't be changed."
        confirmLabel="Submit for good"
        cancelLabel="Not yet"
        confirmVariant="default"
        onConfirm={() => {
          advance();
          void send();
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
