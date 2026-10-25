import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** The title block every sheet starts with. */
export function SheetHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) {
  return (
    <header className="flex flex-col gap-1.5">
      <p className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">{eyebrow}</p>
      <h2 className="font-heading text-2xl font-semibold tracking-tight">{title}</h2>
      {children && <div className="text-muted-foreground">{children}</div>}
    </header>
  );
}

/** A bordered box of the sheet's card grid, with a small uppercase heading. Never split across printed pages. */
export function SheetBox({ heading, id, className, children }: { heading: string; id?: string; className?: string; children: React.ReactNode }) {
  return (
    <Card id={id} className={cn("scroll-mt-20 break-inside-avoid", className)} aria-label={heading} role="region">
      <CardContent className="flex flex-col gap-3">
        <h3 className="font-mono text-xs font-bold tracking-wider text-primary-text uppercase">{heading}</h3>
        {children}
      </CardContent>
    </Card>
  );
}

/** The one idea to take away, across the full width of the grid, in the AI's colour (grape). */
export function RememberBox({ children }: { children: React.ReactNode }) {
  return (
    <section aria-label="Remember" className="break-inside-avoid rounded-[22px] border-[1.5px] border-insight/40 bg-insight-soft px-5 py-4 col-span-full">
      <h3 className="mb-1.5 font-mono text-xs font-bold tracking-wider text-insight-text uppercase">Remember</h3>
      <div className="flex flex-col gap-1.5">{children}</div>
    </section>
  );
}

/** Things that go wrong, each with a coral "!" so they are not mistaken for advice to follow. */
export function MistakeList({ items }: { items: string[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((mistake) => (
        <li key={mistake} className="flex items-start gap-2.5">
          <span aria-hidden="true" className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-destructive-soft text-xs font-extrabold text-destructive-text">
            !
          </span>
          <span className="sr-only">Common mistake: </span>
          <span>{mistake}</span>
        </li>
      ))}
    </ul>
  );
}

/** Formulas, examples and the like sit in a muted box inside a section box. */
export function MutedBox({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("flex flex-col gap-1.5 rounded-xl bg-muted px-3 py-2.5", className)}>{children}</div>;
}
