import { cn } from "@/lib/utils";

/** The row of filters above a page's numbers. */
export function FilterBar({ children, label = "Filters" }: { children: React.ReactNode; label?: string }) {
  return (
    <div role="group" aria-label={label} className="mb-4 flex flex-wrap items-center gap-2">
      {children}
    </div>
  );
}

type SelectProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** The choices after "All". The current value is always offered, even if it is not in the list. */
  options: readonly { value: string; label?: string }[];
  className?: string;
};

/** A labelled drop-down with an "All" choice. A native select: it works with every keyboard and screen reader. */
export function FilterSelect({ label, value, onChange, options, className }: SelectProps) {
  const choices = value && !options.some((option) => option.value === value) ? [{ value }, ...options] : options;
  return (
    <label className={cn("inline-flex items-center gap-1.5 rounded-[10px] border bg-card px-2.5 py-1 text-[13px] font-bold focus-within:ring-3 focus-within:ring-ring/50", className)}>
      <span className="text-muted-foreground">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="max-w-48 truncate bg-transparent text-foreground outline-none">
        <option value="">All</option>
        {choices.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label ?? option.value}
          </option>
        ))}
      </select>
    </label>
  );
}

type DateProps = { label: string; value: string; onChange: (value: string) => void; min?: string; max?: string; invalid?: boolean };

export function FilterDate({ label, value, onChange, min, max, invalid }: DateProps) {
  return (
    <label className={cn("inline-flex items-center gap-1.5 rounded-[10px] border bg-card px-2.5 py-1 text-[13px] font-bold focus-within:ring-3 focus-within:ring-ring/50", invalid && "border-destructive")}>
      <span className="text-muted-foreground">{label}</span>
      <input type="date" value={value} min={min} max={max} aria-invalid={invalid || undefined} onChange={(event) => onChange(event.target.value)} className="bg-transparent font-mono text-[12.5px] text-foreground outline-none" />
    </label>
  );
}
