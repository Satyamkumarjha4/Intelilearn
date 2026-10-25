import { cn } from "cn"

/** A placeholder block while something loads. It only pulses when the learner has not asked for less motion. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="skeleton" aria-hidden="true" className={cn("rounded-xl bg-muted motion-safe:animate-pulse", className)} {...props} />
}

export { Skeleton }
