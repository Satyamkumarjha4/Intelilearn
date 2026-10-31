import { cn } from "@/lib/utils";

type Choice<T extends string> = { id: T; label: string; hint: string };

type Props<T extends string> = {
  name: string;
  legend: string;
  choices: readonly Choice<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  /** Three choices sit in a row from `sm` up; two fit side by side. */
  columns?: 2 | 3;
  children?: React.ReactNode;
};

/** A group of radio cards: one pick from a few, each with a name and a line. The same look for every question the
 *  new-lesson form asks (what to make, which sheets, how to find the level). */
export function ChoiceCards<T extends string>({ name, legend, choices, value, onChange, disabled, columns = 2, children }: Props<T>) {
  return (
    <fieldset className="flex flex-col gap-3" disabled={disabled}>
      <legend className="mb-1 text-sm font-extrabold text-muted-foreground">{legend}</legend>
      <div className={cn("grid gap-3", columns === 3 ? "sm:grid-cols-3" : "sm:grid-cols-2")}>
        {choices.map((choice) => {
          const selected = value === choice.id;
          return (
            <label
              key={choice.id}
              className={cn(
                "flex cursor-pointer flex-col gap-1 rounded-2xl border-2 bg-card px-4 py-3 motion-safe:transition-[box-shadow,background-color,border-color] has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 has-[:disabled]:cursor-default",
                selected ? "border-primary bg-primary-soft shadow-[0_4px_0_var(--primary-deep)]" : "border-border shadow-[0_4px_0_var(--border)] hover:bg-muted",
              )}
            >
              <input type="radio" name={name} value={choice.id} checked={selected} onChange={() => onChange(choice.id)} className="sr-only" />
              <span className="font-heading text-lg font-semibold">{choice.label}</span>
              <span className="text-sm text-muted-foreground">{choice.hint}</span>
            </label>
          );
        })}
      </div>
      {children}
    </fieldset>
  );
}
