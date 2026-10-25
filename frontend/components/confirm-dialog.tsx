"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** `destructive` (the default) for something that cannot be undone; `default` for a change that is easy to take back. */
  confirmVariant?: "destructive" | "default";
  /** True when confirming would do nothing (what it was about has gone); the dialog still opens and closes normally. */
  confirmDisabled?: boolean;
  /** Runs when the learner confirms; the dialog stays open, and both buttons wait, until it settles. */
  onConfirm: () => void | Promise<void>;
};

/** Asks before something that cannot be undone. Used everywhere instead of `window.confirm`. */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, cancelLabel = "Keep going", confirmVariant = "destructive", confirmDisabled = false, onConfirm }: Props) {
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
      onOpenChange(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent showCloseButton={false}>
        <DialogHeader className="pr-0">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button variant={confirmVariant} disabled={busy || confirmDisabled} onClick={confirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
