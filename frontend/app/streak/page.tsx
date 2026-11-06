"use client";

import { FlameIcon, GiftIcon, WrenchIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { useCredits } from "@/components/credits/credits-provider";
import { LoadFailure, PageFrame } from "@/components/credits/page-frame";
import { StreakCalendar } from "@/components/credits/streak-calendar";
import { useLoaded } from "@/components/credits/use-loaded";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { creditsApi } from "@/lib/credits/credits-api";
import { StreakView, type RepairFailure } from "@/lib/credits/streak-view";

export default function StreakPage() {
  const streak = useLoaded(() => creditsApi.streak(), "We couldn't load your streak.");
  const { refresh } = useCredits();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RepairFailure | null>(null);

  const repair = async () => {
    setBusy(true);
    setFailure(null);
    try {
      const done = await creditsApi.repair();
      toast.success(StreakView.repaired(done.day, done.cost, done.bonus));
      streak.reload();
      void refresh();
    } catch (err) {
      setFailure(StreakView.failure(err));
      streak.reload();
    } finally {
      setBusy(false);
    }
  };

  const data = streak.data;
  return (
    <PageFrame eyebrow="Keep going" title="Your streak">
      {streak.error && <LoadFailure message={streak.error} />}
      {!data && !streak.error && <Skeleton className="h-64 rounded-[22px]" aria-busy="true" aria-label="Loading your streak" />}

      {data && (
        <>
          <Card>
            <CardContent className="flex flex-col gap-3">
              <p className="flex items-center gap-2 font-heading text-3xl font-semibold" data-testid="streak-headline">
                <FlameIcon className="size-8 text-marigold-text" aria-hidden="true" /> {StreakView.headline(data)}
              </p>
              <p data-testid="streak-today" data-done={data.today.done}>
                {StreakView.today(data)}
              </p>
              <p className="text-sm text-muted-foreground">{StreakView.best(data)}</p>
              <p className="flex items-center gap-2 text-sm font-bold text-insight-text">
                <GiftIcon className="size-4" aria-hidden="true" /> {StreakView.nextBonus(data)}
              </p>
            </CardContent>
          </Card>

          <section aria-labelledby="days" className="flex flex-col gap-3">
            <h2 id="days" className="font-heading text-xl font-semibold">
              The last 28 days
            </h2>
            <StreakCalendar streak={data} />
          </section>

          <section aria-labelledby="repair" className="flex flex-col gap-3">
            <h2 id="repair" className="font-heading text-xl font-semibold">
              Missed a day?
            </h2>
            {data.repair.available ? (
              <>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="marigold" disabled={busy} onClick={() => void repair()} className="gap-1.5" data-testid="repair-button">
                    <WrenchIcon aria-hidden="true" /> {busy ? "Repairing…" : StreakView.repairTitle(data.repair)}
                  </Button>
                  <p className="text-sm text-muted-foreground">{StreakView.repairLeft(data.repair)}</p>
                </div>
              </>
            ) : (
              <p className="text-muted-foreground" data-testid="repair-reason">
                {StreakView.repairReason(data.repair)} <span className="block text-sm">{StreakView.repairLeft(data.repair)}</span>
              </p>
            )}
            {failure && (
              <Alert variant="destructive" data-testid="repair-failure">
                <AlertDescription>
                  {failure.message}{" "}
                  {failure.buy && (
                    <Link href="/buy" className={buttonVariants({ variant: "link", className: "h-auto p-0" })}>
                      Get more credits
                    </Link>
                  )}
                </AlertDescription>
              </Alert>
            )}
          </section>
        </>
      )}
    </PageFrame>
  );
}
