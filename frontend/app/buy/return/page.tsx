"use client";

import { CheckCircle2Icon, CircleAlertIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";

import { useCredits } from "@/components/credits/credits-provider";
import { PageFrame } from "@/components/credits/page-frame";
import { useOrderWatch } from "@/components/payments/use-order-watch";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { BuyReturn } from "@/lib/payments/buy-return";
import { PaymentWords } from "@/lib/payments/payment-words";
import { WalletWords } from "@/lib/credits/wallet-words";

function Waiting() {
  const params = useSearchParams();
  const orderId = params.get("order");
  const cancelled = params.get("cancelled") === "1";
  const { order, phase, missing } = useOrderWatch(orderId);
  const { balance, refresh } = useCredits();

  // The balance is shown only once the server says the order is fulfilled; this is the moment to fetch it.
  useEffect(() => {
    if (phase === "done") void refresh();
  }, [phase, refresh]);

  if (!orderId || missing) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3">
          <p>We couldn&apos;t find that payment.</p>
          <Link href="/buy" className={buttonVariants()}>
            Back to credits
          </Link>
        </CardContent>
      </Card>
    );
  }

  const Icon = phase === "done" ? CheckCircle2Icon : phase === "failed" ? CircleAlertIcon : Loader2Icon;
  return (
    <Card data-testid="return-card" data-phase={phase}>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-8 text-center" aria-live="polite">
        <Icon
          aria-hidden="true"
          className={phase === "done" ? "size-12 text-success" : phase === "failed" ? "size-12 text-destructive" : "size-12 text-primary motion-safe:animate-spin"}
        />
        <h2 className="font-heading text-2xl font-semibold" data-testid="return-headline">
          {PaymentWords.headline(order, phase)}
        </h2>
        <p className="max-w-prose text-muted-foreground">{PaymentWords.detail(order, phase, cancelled)}</p>
        {phase === "done" && balance && (
          <p className="font-heading text-xl font-semibold" data-testid="return-balance" data-balance={balance.balance}>
            You now have {WalletWords.credits(balance.balance)}.
          </p>
        )}
        <div className="flex flex-wrap justify-center gap-2 pt-2">
          {phase === "done" && (
            <Link href={BuyReturn.recall(window.sessionStorage)} className={buttonVariants({ size: "lg" })} data-testid="return-carry-on">
              Carry on
            </Link>
          )}
          {phase === "done" && (
            <Link href="/wallet" className={buttonVariants({ variant: "outline", size: "lg" })}>
              See my credits
            </Link>
          )}
          {phase === "failed" && (
            <Link href="/buy" className={buttonVariants({ size: "lg" })}>
              Try again
            </Link>
          )}
          {(phase === "waiting" || phase === "slow") && (
            <Link href="/lessons" className={buttonVariants({ variant: "ghost" })}>
              Back to my lessons
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function BuyReturnPage() {
  return (
    <PageFrame eyebrow="Credits" title="Your payment">
      <Suspense fallback={<Button disabled>Checking…</Button>}>
        <Waiting />
      </Suspense>
    </PageFrame>
  );
}
