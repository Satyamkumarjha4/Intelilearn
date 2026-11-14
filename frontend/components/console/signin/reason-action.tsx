"use client";

import { useState } from "react";

import { StackedField } from "@/components/console/field-row";
import { Button } from "@/components/ui/button";
import { ReasonForm } from "@/lib/console-signin/forms";

type Props = {
  id: string;
  title: string;
  /** What this does and what staff must do first (the out-of-band check). */
  warning: React.ReactNode;
  buttonLabel: string;
  busy: boolean;
  /** Called with the trimmed reason once it is long enough. */
  onSubmit: (reason: string) => Promise<boolean>;
};

/** An action that vouches for a person: a typed reason is required, and is kept in the change log. The text stays when
 *  the request fails, and is cleared once it went through. */
export function ReasonAction({ id, title, warning, buttonLabel, busy, onSubmit }: Props) {
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const problem = touched ? ReasonForm.error(reason) : undefined;

  return (
    <form
      aria-label={title}
      onSubmit={async (event) => {
        event.preventDefault();
        setTouched(true);
        if (ReasonForm.error(reason)) return;
        if (await onSubmit(reason.trim())) {
          setReason("");
          setTouched(false);
        }
      }}
      className="grid gap-3 rounded-2xl border bg-card p-[18px] shadow-card"
    >
      <h2 className="font-sans text-base font-extrabold">{title}</h2>
      <p role="note" className="text-[13px] font-semibold text-muted-foreground">
        {warning}
      </p>
      <StackedField id={id} label="Reason (required)" help="At least 10 characters. Kept in the change log." error={problem}>
        <textarea
          id={id}
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? `${id}-error` : undefined}
          className="min-h-16 w-full rounded-[10px] border-[1.5px] bg-card px-2.5 py-1.5 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive"
        />
      </StackedField>
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Working…" : buttonLabel}
        </Button>
      </div>
    </form>
  );
}
