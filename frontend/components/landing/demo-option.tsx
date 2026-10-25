import { cn } from "@/lib/utils";

type Props = {
  /** The number on the option's key. */
  k: number;
  state?: "idle" | "picked" | "right";
  /** Runs the pick-me animation of a preview. */
  animatePick?: boolean;
  /** Only the look, for a preview: not a button, nothing to press. */
  preview?: boolean;
  children: React.ReactNode;
} & Omit<React.ComponentProps<"button">, "children">;

const TONE = {
  idle: "border-border bg-card",
  picked: "border-primary bg-primary-soft shadow-[0_4px_0_var(--primary)]",
  right: "border-success bg-success-soft text-success-text shadow-[0_4px_0_var(--success)]",
};

/** An answer on the landing page's question cards, chunky like the real quick check. A button, or (as a preview) just the look. */
export function DemoOption({ k, state = "idle", animatePick, preview, className, children, ...props }: Props) {
  const look = cn(
    "flex w-full items-center gap-3.5 rounded-2xl border-2 px-3.5 py-3 text-left text-[15px] font-bold shadow-[0_4px_0_var(--border)] outline-none",
    "motion-safe:transition-[transform,box-shadow,border-color,background-color]",
    TONE[state],
    className,
  );
  const key = (
    <span
      aria-hidden="true"
      className={cn(
        "grid size-[30px] shrink-0 place-items-center rounded-[9px] border-2 font-mono text-[13px]",
        state === "picked" ? "border-primary bg-primary text-primary-foreground" : state === "right" ? "border-success" : "border-border text-muted-foreground",
      )}
    >
      {k}
    </span>
  );
  const anim = animatePick && state === "picked" ? "pick" : undefined;

  if (preview) {
    return (
      <div data-anim={anim} className={look}>
        {key}
        {children}
      </div>
    );
  }
  return (
    <button
      type="button"
      data-anim={anim}
      className={cn(look, "focus-visible:ring-3 focus-visible:ring-ring/50", state === "idle" && "enabled:hover:border-primary enabled:active:translate-y-[3px] enabled:active:shadow-[0_1px_0_var(--border)]")}
      {...props}
    >
      {key}
      {children}
    </button>
  );
}
