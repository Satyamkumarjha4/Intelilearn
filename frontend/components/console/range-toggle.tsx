import { cn } from "@/lib/utils";

type Option<T extends string> = { value: T; label: string };
type Props<T extends string> = { options: readonly Option<T>[]; value: T; onChange: (value: T) => void; label?: string };

/** A row of buttons of which one is on: Today / 7 days / 30 days. `aria-pressed` says which. */
export function RangeToggle<T extends string>({ options, value, onChange, label = "Range" }: Props<T>) {
  return (
    <div role="group" aria-label={label} className="inline-flex gap-0.5 rounded-xl bg-muted p-[3px]">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-lg px-3 py-1 text-[13px] font-extrabold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            option.value === value ? "bg-card text-foreground shadow-[0_1px_0_var(--border)]" : "hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
