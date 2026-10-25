import { cn } from "@/lib/utils";

type Props = { title: string; description?: React.ReactNode; actions?: React.ReactNode; className?: string };

/** The title of a console page, what it is for, and its page-wide controls (range, export). */
export function PageHeader({ title, description, actions, className }: Props) {
  return (
    <header className={cn("mb-4 flex flex-wrap items-end justify-between gap-x-4 gap-y-3", className)}>
      <div className="min-w-0">
        <h1 className="text-[26px] max-[560px]:text-[22px]">{title}</h1>
        {description ? <p className="mt-1 text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
