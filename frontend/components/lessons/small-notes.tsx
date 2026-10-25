import { Badge } from "@/components/ui/badge";

/** The builder's small notes, collapsed: they are for the curious, and never an alarm. */
export function SmallNotes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <details className="group rounded-xl border border-border bg-muted/50 px-3 py-2 text-sm">
      <summary className="flex cursor-pointer items-center gap-2 font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        Small notes <Badge variant="secondary">{notes.length}</Badge>
      </summary>
      <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-muted-foreground">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </details>
  );
}
