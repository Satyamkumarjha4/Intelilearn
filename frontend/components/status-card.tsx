import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Props = {
  icon: LucideIcon;
  title: string;
  children?: React.ReactNode;
  /** The buttons under the text. */
  actions?: React.ReactNode;
  tone?: "neutral" | "destructive";
  /** `h2` when the page already has its own title. */
  heading?: "h1" | "h2";
  className?: string;
};

/** The friendly card for "this didn't work" and "there is nothing here": an icon, a plain sentence, what to do next. */
export function StatusCard({ icon: Icon, title, children, actions, tone = "neutral", heading: Heading = "h1", className }: Props) {
  return (
    <Card className={cn("mx-auto w-full max-w-xl", className)}>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-6 text-center">
        <span
          className={cn(
            "grid size-14 place-items-center rounded-full",
            tone === "destructive" ? "bg-destructive-soft text-destructive-text" : "bg-primary-soft text-primary-text",
          )}
        >
          <Icon className="size-7" aria-hidden="true" />
        </span>
        <Heading className="font-heading text-2xl font-semibold tracking-tight">{title}</Heading>
        {children && <div className="flex flex-col gap-2 text-muted-foreground">{children}</div>}
        {actions && <div className="mt-2 flex flex-wrap justify-center gap-3">{actions}</div>}
      </CardContent>
    </Card>
  );
}
