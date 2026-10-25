"use client";

import type { Choice } from "@/lib/onboarding-flow";
import { cn } from "@/lib/utils";
import { tileIcon } from "@/components/profile/tile-icons";

type Props = {
  label: string;
  choices: Choice[];
  value: string;
  onChange: (value: string) => void;
  /** Tiles of just a word (the languages) have no icon and sit closer together. */
  icons?: boolean;
  /** The values are language codes and the labels are each language's own name ("हिन्दी"), so a screen reader says them right. */
  languages?: boolean;
  /** An error from the server about this field. */
  error?: string;
};

/** A question answered by pressing one tile. A pressable tile, an icon, a name and a line of explanation; the chosen
 *  one is primary-soft with a primary border and a flat shadow. */
export function ChoiceTiles({ label, choices, value, onChange, icons = true, languages = false, error }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <div role="radiogroup" aria-label={label} className={cn("grid gap-3", icons ? "sm:grid-cols-2" : "grid-cols-2 sm:grid-cols-3")}>
        {choices.map((choice) => {
          const Icon = tileIcon(choice.value);
          const chosen = value === choice.value;
          return (
            <button
              key={choice.value}
              type="button"
              role="radio"
              aria-checked={chosen}
              onClick={() => onChange(choice.value)}
              className={cn(
                "flex items-center gap-3 rounded-2xl border-2 px-4 py-3 text-left outline-none motion-safe:transition-[transform,box-shadow,background-color] focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-0.5",
                chosen ? "border-primary bg-primary-soft shadow-[0_3px_0_var(--primary)]" : "border-border bg-card shadow-[0_3px_0_var(--border)] hover:bg-muted",
              )}
            >
              {icons && (
                <span className={cn("grid size-10 shrink-0 place-items-center rounded-xl", chosen ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
                  <Icon className="size-5" aria-hidden="true" />
                </span>
              )}
              <span className="flex min-w-0 flex-col">
                <span lang={languages ? choice.value : undefined} className={cn("font-extrabold", !icons && "text-lg")}>
                  {choice.label}
                </span>
                {choice.description && <span className="text-sm text-muted-foreground">{choice.description}</span>}
              </span>
            </button>
          );
        })}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
