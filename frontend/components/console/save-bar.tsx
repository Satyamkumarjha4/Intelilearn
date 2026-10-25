import { Button } from "@/components/ui/button";

type Props = {
  /** Shown while there is something to save. */
  visible: boolean;
  /** What is unsaved, in a few words ("lesson.plan, page.generate"). */
  summary?: string;
  /** A line under it ("New lessons will use these settings"). */
  note?: string;
  saveLabel: string;
  saving?: boolean;
  /** Save is refused while something is invalid. */
  saveDisabled?: boolean;
  onDiscard: () => void;
  onSave: () => void;
};

/** The bar that follows the page down while edits are unsaved: what changed, Discard and Save. */
export function SaveBar({ visible, summary, note, saveLabel, saving = false, saveDisabled = false, onDiscard, onSave }: Props) {
  if (!visible) return null;
  return (
    <div
      role="region"
      aria-label="Unsaved changes"
      className="sticky bottom-3 z-10 mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-2xl bg-foreground px-4 py-3 text-background shadow-card"
    >
      <p className="min-w-0 text-[13px]">
        <b className="text-sm">Unsaved changes</b>
        {summary ? <span className="ml-1.5 font-mono opacity-80 [overflow-wrap:anywhere]">· {summary}</span> : null}
        {note ? <span className="ml-1.5 opacity-75">{note}</span> : null}
      </p>
      <div className="flex gap-2">
        <Button variant="ghost" size="sm" disabled={saving} onClick={onDiscard} className="text-background hover:bg-background/15 hover:text-background">
          Discard
        </Button>
        <Button size="sm" disabled={saving || saveDisabled} onClick={onSave}>
          {saving ? "Saving…" : saveLabel}
        </Button>
      </div>
    </div>
  );
}
