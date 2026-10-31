"use client";

import { LightbulbIcon, SproutIcon, TrendingUpIcon } from "lucide-react";

import { useFollowup } from "@/components/lessons/use-followup";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FollowupOffers } from "@/lib/followup-offer";
import type { FollowupOffer } from "@/lib/types";

type Props = { lessonId: string; offer: FollowupOffer };

/** The offer that goes with a result, kept on the page after the pop-up is skipped (and on any result looked at later):
 *  the same words and the same button. A low rater's suggestion is not a pop-up at all, only this small note. */
export function FollowupOfferCard({ lessonId, offer }: Props) {
  const view = FollowupOffers.view(offer);
  const { busy, take } = useFollowup(lessonId);
  const Icon = offer.kind === "foundation" ? SproutIcon : offer.kind === "advanced" ? TrendingUpIcon : LightbulbIcon;
  return (
    <Card size="sm" aria-label={view.title}>
      <CardContent className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <Icon className="mt-0.5 size-5 shrink-0 text-marigold-text" aria-hidden="true" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <h2 className="font-heading text-base font-semibold">{view.title}</h2>
            <p className="max-w-prose text-sm text-muted-foreground">{view.message}</p>
          </div>
        </div>
        {view.step && (
          <Button variant={offer.kind === "foundation" ? "marigold" : "default"} disabled={busy} onClick={() => void take(view.step!)}>
            {busy ? "Getting ready…" : view.step.label}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
