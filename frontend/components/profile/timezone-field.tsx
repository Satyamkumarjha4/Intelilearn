"use client";

import { useMemo } from "react";

import { FormField } from "@/components/form-field";
import { Input } from "@/components/ui/input";
import { BrowserTimezone } from "@/lib/browser-timezone";

type Props = {
  /** What is typed or picked now. */
  value: string;
  onChange: (zone: string) => void;
  /** The zone saved on the profile ("" when none), so it is always in the list. */
  saved: string;
  /** When the zone can next be changed (ISO instant), or null when it can be changed now. */
  lockedUntil: string | null;
  errors?: string[];
};

const MOST_SHOWN = 60;

/** The learner's time zone: a box that searches the IANA names as you type. It is shut for 30 days after a change. */
export function TimezoneField({ value, onChange, saved, lockedUntil, errors }: Props) {
  const names = useMemo(() => BrowserTimezone.names(undefined, saved, BrowserTimezone.detect()), [saved]);
  const shown = useMemo(() => BrowserTimezone.search(names, value).slice(0, MOST_SHOWN), [names, value]);
  const note = BrowserTimezone.lockNote(lockedUntil, new Date(), BrowserTimezone.initial(saved, BrowserTimezone.detect()));
  const locked = note !== null;

  return (
    <FormField
      id="timezone"
      label="Time zone"
      hint={note ?? `Your day starts at midnight in this zone. ${BrowserTimezone.RULE}`}
      errors={errors}
    >
      <Input
        id="timezone"
        list="timezone-options"
        value={value}
        disabled={locked}
        autoComplete="off"
        spellCheck={false}
        placeholder="Start typing a city, such as Kolkata"
        aria-invalid={!!errors?.length}
        aria-describedby={errors?.length ? "timezone-error" : "timezone-hint"}
        onChange={(event) => onChange(event.target.value)}
      />
      <datalist id="timezone-options">
        {shown.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
    </FormField>
  );
}
