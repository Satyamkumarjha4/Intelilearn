import type { LucideIcon } from "lucide-react";

type Props = { icon: LucideIcon; title: string; description?: React.ReactNode; action?: React.ReactNode };

/** Nothing to show, and why. */
export function EmptyState({ icon: Icon, title, description, action }: Props) {
  return (
    <div className="grid justify-items-center gap-2 rounded-xl px-4 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-full bg-muted text-muted-foreground">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <p className="font-heading text-base font-semibold">{title}</p>
      {description ? <p className="max-w-md text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
