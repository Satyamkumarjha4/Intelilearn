"use client";

import { ArrowLeftIcon, ArrowRightIcon, CheckIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { CostLabel } from "@/components/credits/cost-label";
import { ChoiceCards } from "@/components/lessons/choice-cards";
import { StarRating } from "@/components/lessons/star-rating";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { CostSizes } from "@/lib/credits/cost-sizes";
import { LevelChoice, type LevelSource } from "@/lib/level-choice";
import { lessonsApi } from "@/lib/lessons-api";
import { QuestionTypeCatalog, type TopicKinds } from "@/lib/question-type-catalog";
import { QuizConfigForm, type EligibleLesson, type WizardStep } from "@/lib/quiz-config-form";
import { QuizMessages } from "@/lib/quiz-messages";
import { quizzesApi } from "@/lib/quizzes-api";
import type { QuizQuestionType } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEP_TITLES: Record<WizardStep, string> = {
  source: "What is it about?",
  count: "How many questions?",
  kinds: "What kinds of question?",
  level: "How well do you know it?",
};
const SOURCES = [
  { id: "topic", label: "A topic", hint: "Type anything you want to practise." },
  { id: "lessons", label: "My lessons", hint: "Quiz yourself on lessons you've made." },
] as const satisfies readonly { id: LevelSource; label: string; hint: string }[];

/** The "New quick quiz" wizard: what it is about, how many questions, which kinds, and how to find your level. */
export function QuizWizard() {
  const router = useRouter();
  const [state, setState] = useState(QuizConfigForm.initial);
  const [step, setStep] = useState<WizardStep>("source");
  const [lessons, setLessons] = useState<EligibleLesson[] | null>(null);
  const [judged, setJudged] = useState<TopicKinds>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The lessons a quiz can be made from: the learner's ready lessons that have pages.
  useEffect(() => {
    let active = true;
    lessonsApi
      .list({ stage: "ready", pageSize: 100 })
      .then((page) => active && setLessons(QuizConfigForm.eligible(page.results)))
      .catch(() => active && setLessons([]));
    return () => {
      active = false;
    };
  }, []);

  // Which kinds suit the topic, asked once the learner stops typing. A failure offers every kind.
  const topic = state.source === "topic" ? state.topic.trim() : "";
  useEffect(() => {
    if (topic.length < QuizConfigForm.TOPIC_MIN) return;
    let active = true;
    const timer = setTimeout(() => {
      quizzesApi
        .topicTraits(topic)
        .then((traits) => active && setJudged(traits.source === "fallback" ? null : { numerical: traits.numerical, code: traits.code }))
        .catch(() => active && setJudged(null));
    }, 500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [topic]);

  const known = useMemo(() => lessons ?? [], [lessons]);
  const kinds = QuizConfigForm.kindsFor(state, judged);
  const mode = QuizConfigForm.modeOf(state, known);
  const scored = QuizConfigForm.scores(state, known);
  const at = QuizConfigForm.STEPS.indexOf(step);
  const last = at === QuizConfigForm.STEPS.length - 1;

  // The price follows the choices as they are made, before the form is complete: the count, where the questions come from,
  // and how the level is found are all it depends on.
  const ask = CostSizes.quiz({
    num_questions: state.count,
    source: state.source === "topic" ? { type: "topic", topic: state.topic } : { type: "lessons", lesson_ids: state.lessonIds },
    level: { mode },
  });

  const submit = async () => {
    const request = QuizConfigForm.request(state, known);
    if (!request || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { quiz_id } = await quizzesApi.create(request);
      router.push(`/quizzes/${quiz_id}`);
    } catch (err) {
      setError(QuizMessages.make(err));
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 py-10">
      <div className="flex flex-col gap-2 text-center">
        <h1 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">New quick quiz</h1>
        <p className="text-muted-foreground">A few questions to see where you are. Take it as often as you like: every try has new questions.</p>
      </div>

      <ol className="flex items-center justify-center gap-2" aria-label="Steps">
        {QuizConfigForm.STEPS.map((one, index) => (
          <li key={one} className="flex items-center gap-2" aria-current={one === step ? "step" : undefined}>
            <span
              className={cn(
                "grid size-7 place-items-center rounded-full border-2 text-xs font-extrabold",
                index < at ? "border-primary bg-primary text-primary-foreground" : one === step ? "border-primary bg-primary-soft text-primary-text" : "border-border text-muted-foreground",
              )}
            >
              {index < at ? <CheckIcon className="size-4" aria-hidden="true" /> : index + 1}
            </span>
            <span className={cn("hidden text-sm font-bold sm:inline", one === step ? "text-foreground" : "text-muted-foreground")}>{STEP_TITLES[one].replace("?", "")}</span>
          </li>
        ))}
      </ol>

      {error && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <section aria-labelledby="step-heading" className="flex flex-col gap-5">
        <h2 id="step-heading" className="font-heading text-2xl font-semibold">{STEP_TITLES[step]}</h2>

        {step === "source" && (
          <>
            <ChoiceCards
              name="source"
              legend="Make the quiz from"
              choices={SOURCES}
              value={state.source}
              onChange={(source) => setState((s) => QuizConfigForm.setSource(s, source))}
            />
            {state.source === "topic" ? (
              <div className="flex flex-col gap-1.5">
                <label htmlFor="quiz-topic" className="sr-only">
                  Topic
                </label>
                <Input
                  id="quiz-topic"
                  value={state.topic}
                  maxLength={QuizConfigForm.TOPIC_MAX}
                  placeholder="For example: Binary search"
                  autoComplete="off"
                  onChange={(e) => setState((s) => ({ ...s, topic: e.target.value }))}
                />
              </div>
            ) : (
              <LessonPicker lessons={lessons} state={state} onToggle={(id) => setState((s) => QuizConfigForm.toggleLesson(s, id))} />
            )}
          </>
        )}

        {step === "count" && (
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">Number of questions</legend>
            <div className="flex flex-wrap gap-2">
              {QuizConfigForm.counts(state).map((count) => (
                <button
                  key={count}
                  type="button"
                  aria-pressed={state.count === count}
                  onClick={() => setState((s) => QuizConfigForm.setCount(s, count, kinds))}
                  className={cn(
                    "min-w-16 rounded-2xl border-2 px-4 py-3 font-heading text-xl font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    state.count === count ? "border-primary bg-primary-soft text-primary-text" : "border-border bg-card hover:bg-muted",
                  )}
                >
                  {count}
                </button>
              ))}
            </div>
            {state.source === "lessons" && state.lessonIds.length > 1 && (
              <p className="text-sm text-muted-foreground">Each of your {state.lessonIds.length} lessons gets at least one question, so there are no smaller choices.</p>
            )}
          </fieldset>
        )}

        {step === "kinds" && (
          <fieldset className="flex flex-col gap-3">
            <legend className="sr-only">Kinds of question</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {QuestionTypeCatalog.offered(kinds, state.count).map((option) => (
                <KindToggle
                  key={option.id}
                  id={option.id}
                  label={option.label}
                  hint={option.hint}
                  checked={state.types.includes(option.id)}
                  onToggle={() => setState((s) => QuizConfigForm.toggleKind(s, option.id))}
                />
              ))}
            </div>
            {QuestionTypeCatalog.note(kinds, state.count) && <p className="text-sm text-muted-foreground">{QuestionTypeCatalog.note(kinds, state.count)}</p>}
          </fieldset>
        )}

        {step === "level" && (
          <ChoiceCards
            name="level"
            legend="Find my level by"
            columns={3}
            choices={LevelChoice.options(state.source).map((option) => ({
              ...option,
              hint: LevelChoice.unavailable(option.id, state.source, scored) ?? option.hint,
            }))}
            value={mode}
            onChange={(picked) => {
              if (LevelChoice.unavailable(picked, state.source, scored) === null) setState((s) => QuizConfigForm.setMode(s, picked));
            }}
          >
            {mode === "self_rating" && <StarRating value={state.rating} onChange={(rating) => setState((s) => QuizConfigForm.setRating(s, rating))} />}
            {mode === "calibration" && <p className="text-sm text-muted-foreground">You&apos;ll answer five questions first, each a little harder or easier than the last. Then your quiz is written for the level they find.</p>}
          </ChoiceCards>
        )}
      </section>

      <CostLabel ask={ask} breakdown={last} className="items-center self-center text-center" />

      <div className="flex items-center justify-between gap-3">
        <Button type="button" variant="ghost" disabled={at === 0 || busy} onClick={() => setStep(QuizConfigForm.STEPS[at - 1])}>
          <ArrowLeftIcon /> Back
        </Button>
        {last ? (
          <Button type="button" size="lg" disabled={!QuizConfigForm.ready(state, known) || busy} onClick={() => void submit()}>
            {busy ? "Making your quiz…" : "Make my quiz"} <ArrowRightIcon />
          </Button>
        ) : (
          <Button type="button" size="lg" disabled={!QuizConfigForm.stepReady(step, state, known)} onClick={() => setStep(QuizConfigForm.STEPS[at + 1])}>
            Next <ArrowRightIcon />
          </Button>
        )}
      </div>
    </main>
  );
}

function KindToggle({ id, label, hint, checked, onToggle }: { id: QuizQuestionType; label: string; hint: string; checked: boolean; onToggle: () => void }) {
  return (
    <label
      className={cn(
        "flex cursor-pointer flex-col gap-1 rounded-2xl border-2 bg-card px-4 py-3 has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50",
        checked ? "border-primary bg-primary-soft" : "border-border hover:bg-muted",
      )}
    >
      <input type="checkbox" name="kinds" value={id} checked={checked} onChange={onToggle} className="sr-only" />
      <span className="flex items-center justify-between font-heading text-lg font-semibold">
        {label}
        {checked && <CheckIcon className="size-4 text-primary-text" aria-hidden="true" />}
      </span>
      <span className="text-sm text-muted-foreground">{hint}</span>
    </label>
  );
}

function LessonPicker({ lessons, state, onToggle }: { lessons: EligibleLesson[] | null; state: ReturnType<typeof QuizConfigForm.initial>; onToggle: (id: string) => void }) {
  if (lessons === null) return <Skeleton className="h-32 rounded-2xl" aria-label="Loading your lessons" />;
  if (lessons.length === 0) {
    return <p className="rounded-2xl border-2 border-dashed border-border px-4 py-6 text-center text-muted-foreground">You don&apos;t have a finished lesson yet. Make one first, or quiz yourself on a topic.</p>;
  }
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-extrabold text-muted-foreground">
        Pick up to {QuizConfigForm.MAX_LESSONS} lessons · {state.lessonIds.length} picked
      </legend>
      <ul className="flex flex-col gap-2">
        {lessons.map((lesson) => {
          const picked = state.lessonIds.includes(lesson.id);
          const blocked = !QuizConfigForm.canAddLesson(state, lesson.id);
          return (
            <li key={lesson.id}>
              <label
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-2xl border-2 bg-card px-4 py-2.5 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60 has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50",
                  picked ? "border-primary bg-primary-soft" : "border-border hover:bg-muted",
                )}
              >
                <input type="checkbox" checked={picked} disabled={blocked} onChange={() => onToggle(lesson.id)} className="size-4 accent-primary" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{lesson.title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {lesson.level ? `${lesson.level.charAt(0).toUpperCase()}${lesson.level.slice(1)} level` : "Level not set"} · {lesson.scored ? "has a test score" : "no test taken yet"}
                  </span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
