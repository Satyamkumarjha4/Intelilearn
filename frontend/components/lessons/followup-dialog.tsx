"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useFollowup } from "@/components/lessons/use-followup";
import { FollowupOffers } from "@/lib/followup-offer";
import type { FollowupOffer } from "@/lib/types";

type Props = { lessonId: string; offer: FollowupOffer; open: boolean; onOpenChange: (open: boolean) => void };

/** The pop-up after a result that suggests a Foundation or an Advanced lesson: one message, skippable, and the one thing
 *  the server chose (make the lesson, or open the one that exists). */
export function FollowupDialog({ lessonId, offer, open, onOpenChange }: Props) {
  const view = FollowupOffers.view(offer);
  const { busy, take } = useFollowup(lessonId);
  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent showCloseButton={false}>
        <DialogHeader className="pr-0">
          <DialogTitle>{view.title}</DialogTitle>
          <DialogDescription>{view.message}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            {view.skip}
          </Button>
          {view.step && (
            <Button variant={offer.kind === "foundation" ? "marigold" : "default"} disabled={busy} onClick={() => void take(view.step!)}>
              {busy ? "Getting ready…" : view.step.label}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
