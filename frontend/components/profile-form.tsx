"use client";

import { useState } from "react";

import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type FieldErrors } from "@/lib/api";
import { EDUCATION_LEVELS, GOALS, LANGUAGES, LEARNING_PREFERENCES } from "@/lib/profile-options";
import type { Profile, ProfileInput } from "@/lib/types";

type ProfileFormProps = {
  initial: Profile;
  submitLabel: string;
  showAccountFields?: boolean;
  onSaved: (profile: Profile) => void;
};

function ChoiceField({
  id,
  label,
  options,
  value,
  onChange,
  errors,
}: {
  id: string;
  label: string;
  options: Record<string, string>;
  value: string;
  onChange: (value: string) => void;
  errors?: string[];
}) {
  return (
    <FormField id={id} label={label} errors={errors}>
      <Select items={options} value={value || null} onValueChange={(next) => onChange(next ? String(next) : "")}>
        <SelectTrigger id={id} className="w-full" aria-invalid={!!errors}>
          <SelectValue placeholder="Choose one" />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(options).map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

export function ProfileForm({ initial, submitLabel, showAccountFields = false, onSaved }: ProfileFormProps) {
  const [values, setValues] = useState<ProfileInput>({
    name: initial.name,
    education_level: initial.education_level,
    grade_or_year: initial.grade_or_year,
    field_of_study: initial.field_of_study,
    preferred_language: initial.preferred_language || "en",
    learning_preference: initial.learning_preference,
    goal: initial.goal,
    notes: initial.notes,
  });
  const [fields, setFields] = useState<FieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof ProfileInput>(key: K, value: ProfileInput[K]) =>
    setValues((current) => ({ ...current, [key]: value }));

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setFields({});
    try {
      const body = showAccountFields ? values : { ...values, name: undefined };
      onSaved(await api<Profile>("/profile", { method: "PUT", body }));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        setFields(err.fields);
      } else {
        setError("Something went wrong. Check your connection and try again.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {showAccountFields && (
        <div className="grid gap-5 sm:grid-cols-2">
          <FormField id="name" label="Name" errors={fields.name}>
            <Input id="name" value={values.name} onChange={(e) => set("name", e.target.value)} aria-invalid={!!fields.name} />
          </FormField>
          <FormField id="email" label="Email" hint="Your sign-in email can't be changed.">
            <Input id="email" value={initial.email} disabled />
          </FormField>
        </div>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        <ChoiceField
          id="education_level"
          label="Where are you in your education?"
          options={EDUCATION_LEVELS}
          value={values.education_level}
          onChange={(v) => set("education_level", v as ProfileInput["education_level"])}
          errors={fields.education_level}
        />
        <FormField id="grade_or_year" label="Grade or year" hint="For example: Class 10, 2nd year B.Tech" errors={fields.grade_or_year}>
          <Input id="grade_or_year" value={values.grade_or_year} onChange={(e) => set("grade_or_year", e.target.value)} />
        </FormField>
        <FormField id="field_of_study" label="Field of study" hint="Helps us pick relevant examples" errors={fields.field_of_study}>
          <Input id="field_of_study" value={values.field_of_study} onChange={(e) => set("field_of_study", e.target.value)} />
        </FormField>
        <ChoiceField
          id="preferred_language"
          label="Lesson language"
          options={LANGUAGES}
          value={values.preferred_language}
          onChange={(v) => set("preferred_language", v)}
          errors={fields.preferred_language}
        />
        <ChoiceField
          id="learning_preference"
          label="How do you learn best?"
          options={LEARNING_PREFERENCES}
          value={values.learning_preference}
          onChange={(v) => set("learning_preference", v as ProfileInput["learning_preference"])}
          errors={fields.learning_preference}
        />
        <ChoiceField
          id="goal"
          label="What's your main goal?"
          options={GOALS}
          value={values.goal}
          onChange={(v) => set("goal", v as ProfileInput["goal"])}
          errors={fields.goal}
        />
      </div>

      <FormField
        id="notes"
        label="Anything else we should know?"
        hint="Optional: what you already know, what you struggle with, upcoming exams…"
        errors={fields.notes}
      >
        <Textarea id="notes" rows={3} value={values.notes} onChange={(e) => set("notes", e.target.value)} />
      </FormField>

      <Button type="submit" disabled={saving} className="self-start">
        {saving ? "Saving…" : submitLabel}
      </Button>
    </form>
  );
}
