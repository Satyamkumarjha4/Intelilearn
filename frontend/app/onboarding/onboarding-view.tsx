"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand/logo";
import { TopicStep } from "@/components/onboarding/topic-step";
import { ChoiceTiles } from "@/components/profile/choice-tiles";
import { StudyFollowUp } from "@/components/profile/study-follow-up";
import { useProfile } from "@/components/use-profile";
import { useProfileOptions } from "@/components/use-profile-options";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { apiClient, ApiError, type FieldErrors } from "@/lib/api";
import { lessonsApi } from "@/lib/lessons-api";
import { NewLesson } from "@/lib/new-lesson";
import { OnboardingFlow, OnboardingStore } from "@/lib/onboarding-flow";
import { PendingTopic } from "@/lib/pending-topic";
import { SetupMarker } from "@/lib/setup-marker";
import type { Profile } from "@/lib/types";
import { TopicPick } from "@/lib/topic-suggestions";
import { cn } from "@/lib/utils";

const TITLES = [
  "Where are you in your studies?",
  "How do you learn best?",
  "What's your main goal?",
  "Which language should your lessons be in?",
];
const LEADS: Record<number, string> = {
  2: "Visual learners get more graphs, diagrams and animations in their lessons.",
};

/** The five-step setup. Its place is kept in `sessionStorage`, Back is allowed, and Continue on step 4 saves the profile. */
export function OnboardingView({ next }: { next: string }) {
  // The saved place lives in this browser only, so nothing is drawn from it until the page is on the client (the server's
  // markup and the first client render must match).
  const mounted = useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false,
  );
  return mounted ? <Loaded next={next} /> : <Shell><Skeleton className="h-72 rounded-[22px]" /></Shell>;
}

function Loaded({ next }: { next: string }) {
  const { profile, error } = useProfile();
  const [store] = useState(() => new OnboardingStore());
  // A refresh resumes from the stored place; otherwise the setup starts from what the profile already says.
  const [saved] = useState(() => store.load());
  if (error) {
    return (
      <Shell>
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </Shell>
    );
  }
  if (!profile && !saved) {
    return (
      <Shell>
        <Skeleton className="h-72 rounded-[22px]" />
      </Shell>
    );
  }
  return <Steps next={next} store={store} start={saved ?? OnboardingFlow.fromProfile(profile as Profile)} />;
}

function Steps({ next, store, start }: { next: string; store: OnboardingStore; start: OnboardingFlow }) {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const choices = useProfileOptions();
  const [flow, setFlow] = useState(start);
  const [fields, setFields] = useState<FieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending] = useState(() => new PendingTopic());
  const [marker] = useState(() => new SetupMarker());
  const [pick, setPick] = useState(() => new TopicPick().type(pending.peek() ?? ""));
  const stage = useRef<HTMLDivElement>(null);
  const first = user?.name.trim().split(/\s+/)[0] ?? "";

  const update = (changes: Parameters<OnboardingFlow["with"]>[0]) => {
    setFlow((current) => {
      const changed = current.with(changes);
      store.save(changed);
      return changed;
    });
    setFields({});
  };
  const go = (move: (current: OnboardingFlow) => OnboardingFlow) => {
    setFlow((current) => {
      const moved = move(current);
      store.save(moved);
      return moved;
    });
    setError(null);
  };

  // The topic typed on the landing page stays offered until the setup ends, so a refresh on the last step keeps it.
  const finish = () => {
    pending.take();
    marker.end();
    store.clear();
  };

  // Each step slides in from the side the learner came from (not at all for reduced motion), and takes focus.
  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const from = flow.direction === "back" ? -28 : 28;
      node.animate?.([{ transform: `translateX(${from}px)`, opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 220, easing: "ease-out" });
    }
    node.querySelector<HTMLElement>("h1")?.focus({ preventScroll: true });
  }, [flow.step, flow.direction]);

  const saveProfile = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await apiClient.request<Profile>("/profile", { method: "PUT", body: flow.profile() });
      if (user) setUser({ ...user, profile_complete: saved.profile_complete });
      marker.begin(); // the profile is saved now, so the guard must let a refresh stay on the last step
      go((current) => current.next());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't save that. Check your connection and try again.");
      setFields(err instanceof ApiError ? err.fields : {});
    } finally {
      setBusy(false);
    }
  };

  const onContinue = () => (flow.step === 4 ? void saveProfile() : go((current) => current.next()));

  const start5 = async () => {
    setBusy(true);
    setError(null);
    try {
      const { lesson_id } = await lessonsApi.create(pick.topic(), "");
      finish();
      router.push(`/lessons/${lesson_id}`);
    } catch (err) {
      setError(NewLesson.errorMessage(err));
      setBusy(false);
    }
  };

  const later = () => {
    finish();
    router.push(next);
  };

  const a = flow.answers;
  return (
    <Shell step={flow.step}>
      <div ref={stage} className="flex flex-col gap-6">
        {flow.step < 5 && (
          <div className="flex flex-col gap-2">
            {flow.step === 1 && first && <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">Hi {first}! Let&apos;s set up your lessons</p>}
            <h1 tabIndex={-1} className="font-heading text-3xl font-semibold tracking-tight outline-none">
              {TITLES[flow.step - 1]}
            </h1>
            {LEADS[flow.step] && <p className="text-muted-foreground">{LEADS[flow.step]}</p>}
          </div>
        )}
        {flow.step < 5 && error && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {flow.step === 1 && (
          <>
            <ChoiceTiles label="Where are you in your studies?" choices={choices("education_level")} value={a.education_level} onChange={(value) => update({ education_level: value as never })} error={fields.education_level?.[0]} />
            <StudyFollowUp
              level={a.education_level}
              grade={a.grade_or_year}
              field={a.field_of_study}
              onGrade={(value) => update({ grade_or_year: value })}
              onField={(value) => update({ field_of_study: value })}
              errors={{ grade: fields.grade_or_year?.[0], field: fields.field_of_study?.[0] }}
            />
          </>
        )}
        {flow.step === 2 && <ChoiceTiles label="How do you learn best?" choices={choices("learning_preference")} value={a.learning_preference} onChange={(value) => update({ learning_preference: value as never })} error={fields.learning_preference?.[0]} />}
        {flow.step === 3 && <ChoiceTiles label="What's your main goal?" choices={choices("goal")} value={a.goal} onChange={(value) => update({ goal: value as never })} error={fields.goal?.[0]} />}
        {flow.step === 4 && (
          <>
            <ChoiceTiles label="Lesson language" icons={false} languages choices={choices("preferred_language")} value={a.preferred_language} onChange={(value) => update({ preferred_language: value })} error={fields.preferred_language?.[0]} />
            <div className="flex flex-col gap-2">
              <label htmlFor="notes" className="text-sm font-extrabold text-muted-foreground">
                Anything else we should know? (optional)
              </label>
              <Textarea id="notes" rows={3} maxLength={2000} value={a.notes} onChange={(e) => update({ notes: e.target.value })} placeholder="An exam coming up, what you already know, what you find hard…" />
              {fields.notes && <p className="text-sm text-destructive">{fields.notes[0]}</p>}
            </div>
          </>
        )}
        {flow.step === 5 && <TopicStep summary={flow.summary()} answers={flow.suggestionAnswers()} pick={pick} onPick={setPick} onChange={() => go((current) => current.goTo(1))} error={error} />}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        {flow.step > 1 ? (
          <Button variant="ghost" onClick={() => go((current) => current.back())} disabled={busy}>
            ← Back
          </Button>
        ) : (
          <span />
        )}
        {flow.step < 5 ? (
          <Button size="lg" onClick={onContinue} disabled={!flow.canContinue || busy} className="h-11 px-6">
            {flow.step === 4 && busy ? "Saving…" : "Continue"}
          </Button>
        ) : (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="ghost" onClick={later} disabled={busy}>
              I&apos;ll do this later
            </Button>
            <Button size="lg" onClick={start5} disabled={!pick.canStart || busy} className="h-11 px-6">
              {busy ? "Starting…" : "Start my quick check"}
            </Button>
          </div>
        )}
      </div>
    </Shell>
  );
}

/** A focused page: no app navigation, just the mark, the progress and the step. */
function Shell({ step, children }: { step?: number; children: React.ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-8 px-4 py-6">
      <header className="flex items-center gap-4">
        <Link href="/" aria-label="Socra home" className="rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <Logo variant="mark" size="sm" />
        </Link>
        {step && (
          <>
            <ol role="progressbar" aria-label="Setup progress" aria-valuemin={1} aria-valuemax={5} aria-valuenow={step} className="flex flex-1 gap-1.5">
              {[1, 2, 3, 4, 5].map((n) => (
                <li key={n} className={cn("h-2.5 flex-1 rounded-full", n < step ? "bg-primary" : n === step ? "bg-primary-soft ring-2 ring-primary" : "bg-muted")} />
              ))}
            </ol>
            <span className="font-mono text-sm text-muted-foreground tabular-nums">{step} / 5</span>
          </>
        )}
      </header>
      {children}
    </main>
  );
}
