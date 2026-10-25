import { cn } from "cn"

type Props = {
  /** 0 to 1. Leave it out with `indeterminate`. */
  value?: number
  className?: string
  label: string
  /** The progress cannot be measured yet: a segment sweeps along the bar (and sits still for reduced motion). */
  indeterminate?: boolean
}

/** A chunky progress bar. */
function Progress({ value = 0, className, label, indeterminate = false }: Props) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100)
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : percent}
      className={cn("h-3 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      {indeterminate ? (
        <div className="progress-indeterminate h-full w-2/5 rounded-full bg-primary shadow-[inset_0_2px_0_color-mix(in_oklch,var(--primary-foreground)_35%,transparent)]" />
      ) : (
        <div className="h-full rounded-full bg-primary shadow-[inset_0_2px_0_color-mix(in_oklch,var(--primary-foreground)_35%,transparent)] motion-safe:transition-all" style={{ width: `${percent}%` }} />
      )}
    </div>
  )
}

export { Progress }
