"use client";

import { forwardRef } from "react";

import { CodeEntry } from "@/lib/code-entry";
import { cn } from "@/lib/utils";

type CodeBoxesProps = {
  id: string;
  label: string;
  value: string;
  onChange: (digits: string) => void;
  invalid?: boolean;
  describedBy?: string;
};

/**
 * The box for an emailed code, drawn as six boxes over one real input (`autocomplete="one-time-code"`, numeric keypad): a
 * paste of `123 456` works and only the digits stay (`CodeEntry`). Used by the code screen and the new-password screen.
 */
export const CodeBoxes = forwardRef<HTMLInputElement, CodeBoxesProps>(function CodeBoxes({ id, label, value, onChange, invalid, describedBy }, ref) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-extrabold">
        {label}
      </label>
      <div className="relative focus-within:[&>div]:border-ring">
        <div className="grid grid-cols-6 gap-2" aria-hidden="true">
          {CodeEntry.boxes(value).map((digit, index) => (
            <div
              key={index}
              className={cn(
                "grid h-14 place-items-center rounded-xl border-[1.5px] border-border bg-background font-mono text-2xl font-bold",
                index === value.length && "border-ring ring-3 ring-ring/40",
              )}
            >
              {digit}
            </div>
          ))}
        </div>
        <input
          ref={ref}
          id={id}
          name="code"
          value={value}
          onChange={(event) => onChange(CodeEntry.digits(event.target.value))}
          autoComplete="one-time-code"
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={14}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          className="absolute inset-0 h-full w-full cursor-text opacity-0"
        />
      </div>
    </div>
  );
});
