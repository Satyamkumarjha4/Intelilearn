import { cn } from "cn"

/** A thin progress bar. `value` is 0 to 1. */
function Progress({ value, className, label }: { value: number; className?: string; label: string }) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100)
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percent}%` }} />
    </div>
  )
}

export { Progress }
