"use client";

import { useState } from "react";
import { FormField } from "@/components/form-field";
import { ChoiceTiles } from "@/components/profile/choice-tiles";
import { StudyFollowUp } from "@/components/profile/study-follow-up";
import { useProfileOptions } from "@/components/use-profile-options";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiClient, ApiError, type FieldErrors } from "@/lib/api";
import { OnboardingFlow } from "@/lib/onboarding-flow";
import type { Profile } from "@/lib/types";

type Props = { initial: Profile; onSaved: (profile: Profile) => void };

/** The whole profile on one page, with the same tiles and follow-up questions as the setup, plus name and email. */
export function ProfileEditor({ initial, onSaved }: Props) {
  const choices = useProfileOptions();
  const [flow, setFlow] = useState(() => OnboardingFlow.fromProfile(initial));
  const [name, setName] = useState(initial.name);
  const [fields, setFields] = useState<FieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const a = flow.answers;
  const update = (changes: Parameters<OnboardingFlow["with"]>[0]) => {
    setFlow((current) => current.with(changes));
    setFields({});
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return setFields({ name: ["Tell us your name."] });
    if (!flow.complete) return setError("Please answer each question first.");
    setSaving(true);
    setError(null);
    setFields({});
    try {
      onSaved(await apiClient.request<Profile>("/profile", { method: "PUT", body: { name: name.trim(), ...flow.profile() } }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't save that. Check your connection and try again.");
      setFields(err instanceof ApiError ? err.fields : {});
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={save} className="flex flex-col gap-8" noValidate>
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        <FormField id="name" label="Name" errors={fields.name}>
          <Input id="name" value={name} autoComplete="name" onChange={(e) => setName(e.target.value)} aria-invalid={!!fields.name} />
        </FormField>
        <FormField id="email" label="Email" hint="Your sign-in email can't be changed.">
          <Input id="email" value={initial.email} disabled />
        </FormField>
      </div>

      <Section title="Where are you in your studies?">
        <ChoiceTiles label="Where are you in your studies?" choices={choices("education_level")} value={a.education_level} onChange={(value) => update({ education_level: value as never })} error={fields.education_level?.[0]} />
        <StudyFollowUp
          level={a.education_level}
          grade={a.grade_or_year}
          field={a.field_of_study}
          onGrade={(value) => update({ grade_or_year: value })}
          onField={(value) => update({ field_of_study: value })}
          errors={{ grade: fields.grade_or_year?.[0], field: fields.field_of_study?.[0] }}
        />
      </Section>
      <Section title="How do you learn best?">
        <ChoiceTiles label="How do you learn best?" choices={choices("learning_preference")} value={a.learning_preference} onChange={(value) => update({ learning_preference: value as never })} error={fields.learning_preference?.[0]} />
      </Section>
      <Section title="What's your main goal?">
        <ChoiceTiles label="What's your main goal?" choices={choices("goal")} value={a.goal} onChange={(value) => update({ goal: value as never })} error={fields.goal?.[0]} />
      </Section>
      <Section title="Which language should your lessons be in?">
        <ChoiceTiles label="Lesson language" icons={false} languages choices={choices("preferred_language")} value={a.preferred_language} onChange={(value) => update({ preferred_language: value })} error={fields.preferred_language?.[0]} />
      </Section>

      <FormField id="notes" label="Anything else we should know? (optional)" hint="What you already know, what you find hard, upcoming exams…" errors={fields.notes}>
        <Textarea id="notes" rows={3} maxLength={2000} value={a.notes} onChange={(e) => update({ notes: e.target.value })} />
      </FormField>

      <Button type="submit" size="lg" disabled={saving} className="h-11 self-start px-6">
        {saving ? "Saving…" : "Save changes"}
      </Button>
    </form>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-heading text-xl font-semibold">{title}</h2>
      {children}
    </section>
  );
}
