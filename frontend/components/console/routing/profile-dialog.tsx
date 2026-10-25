import { ArrowRightIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { type ProfileChange, RoutingProfile } from "@/lib/routing-profile";
import type { ProfilePreview } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  preview: ProfilePreview | null;
  /** Steps with edits the profile would replace. */
  editedKeys: ReadonlySet<string>;
  onApply: () => void;
  onClose: () => void;
};

function Chain({ models }: { models: readonly string[] }) {
  return <span className="font-mono text-xs [overflow-wrap:anywhere]">{models.map((m) => m.split("/").slice(1).join("/") || m).join(" → ")}</span>;
}

function Row({ change, replacesEdits }: { change: ProfileChange; replacesEdits: boolean }) {
  return (
    <li className={cn("grid gap-1 rounded-xl border px-3 py-2", change.blocked && "border-destructive/30 bg-destructive-soft")}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <b className="font-mono text-[12.5px]">{change.key}</b>
        {change.blocked ? <span className="text-xs font-extrabold text-destructive-text">Cannot be applied</span> : replacesEdits ? <span className="text-xs font-bold text-marigold-text">Replaces your unsaved edit</span> : null}
      </div>
      {change.chain ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-2 gap-y-0.5">
          <dt className="text-xs font-bold text-muted-foreground">Now</dt>
          <dd><Chain models={change.chain.before} /></dd>
          <dt className="text-xs font-bold text-muted-foreground">Then</dt>
          <dd><Chain models={change.chain.after} /></dd>
        </dl>
      ) : null}
      {change.effort ? (
        <p className="text-xs font-semibold text-muted-foreground">
          Effort: {change.effort.before} <ArrowRightIcon className="inline size-3" aria-label="becomes" /> {change.effort.after}
        </p>
      ) : null}
      {change.enabled ? (
        <p className="text-xs font-semibold text-muted-foreground">{change.enabled.after ? "Switched on" : "Switched off"}</p>
      ) : null}
      {change.problems.map((problem) => (
        <p key={problem} className="text-xs font-bold text-destructive-text">
          {problem}
        </p>
      ))}
    </li>
  );
}

/** What a profile would change, step by step. Applying only loads it into the editor: nothing is saved until Save. */
export function ProfileDialog({ preview, editedKeys, onApply, onClose }: Props) {
  const changes = preview ? RoutingProfile.changes(preview) : [];
  const usable = changes.filter((change) => !change.blocked).length;
  return (
    <Dialog open={preview !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{preview ? `Apply “${preview.label}”?` : "Apply a profile"}</DialogTitle>
          <DialogDescription>
            {RoutingProfile.summary(changes)}. Applying loads the changes into the editor so you can look them over; nothing is saved until you press Save routing.
          </DialogDescription>
        </DialogHeader>
        {changes.length ? (
          <ul className="grid gap-2" aria-label="Steps this profile changes">
            {changes.map((change) => (
              <Row key={change.key} change={change} replacesEdits={editedKeys.has(change.key)} />
            ))}
          </ul>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={usable === 0} onClick={onApply}>
            {usable === 1 ? "Load 1 step" : `Load ${usable} steps`} into the editor
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
