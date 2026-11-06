"use client";

import { CoinsIcon } from "lucide-react";
import Link from "next/link";

import { useCredits } from "@/components/credits/credits-provider";
import { useQuote } from "@/components/credits/use-quote";
import { cn } from "@/lib/utils";
import { CostWords } from "@/lib/credits/cost-words";
import type { CostAsk } from "@/lib/credits/cost-sizes";
import type { Quote } from "@/lib/credits/types";

type Props = {
  /** What is about to start (build it with `CostSizes`); null to ask nothing. */
  ask: CostAsk | null;
  /** For the Retry on a failed lesson: the lesson, in place of `ask`. */
  retryLessonId?: string;
  /** Say what the price is made of, under it. */
  breakdown?: boolean;
  /** The product's sentence for the mastery choice of a lesson only. */
  halfBack?: boolean;
  className?: string;
};

/**
 * What an action will cost, shown before it is clicked. The number is the server's (`POST /credits/quote`), the same one
 * the credit gate charges; a screen never works out a price. If the learner cannot pay what is due now it says so, with
 * a way to buy, but the button next to it stays enabled: the server decides when it is pressed.
 */
export function CostLabel({ ask, retryLessonId, breakdown = false, halfBack = false, className }: Props) {
  const quote = useQuote(ask, retryLessonId);
  const { balance } = useCredits();

  if (quote === null) return null; // no price to show; never block the action
  if (quote === undefined) {
    return (
      <span className={cn("inline-flex h-6 w-24 animate-pulse rounded-full bg-muted motion-reduce:animate-none", className)} aria-hidden="true" data-testid="cost-label-loading" />
    );
  }
  const short = balance !== null && !CostWords.affordable(quote, balance.balance);
  return <Priced quote={quote} short={short} balance={balance?.balance ?? 0} breakdown={breakdown} halfBack={halfBack} className={className} />;
}

function Priced({ quote, short, balance, breakdown, halfBack, className }: { quote: Quote; short: boolean; balance: number; breakdown: boolean; halfBack: boolean; className?: string }) {
  const free = quote.exempt || quote.total === 0;
  const text = free ? CostWords.of(quote) : `Costs ${CostWords.of(quote)}`;
  const parts = breakdown ? CostWords.breakdown(quote) : "";
  return (
    <span className={cn("inline-flex flex-col gap-0.5 text-sm", className)} data-testid="cost-label" data-credits={quote.due_now} data-total={quote.total}>
      <span
        className={cn(
          "inline-flex w-fit max-w-full items-center gap-1.5 rounded-full px-2.5 py-0.5 font-bold",
          short ? "bg-destructive-soft text-destructive-text" : "bg-marigold-soft text-marigold-text",
        )}
      >
        <CoinsIcon className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0">{text}</span>
      </span>
      {parts ? <span className="text-xs text-muted-foreground">{parts}</span> : null}
      {halfBack ? <span className="text-xs font-bold text-success-text">{CostWords.HALF_BACK}</span> : null}
      {short ? (
        <span className="text-xs text-muted-foreground" role="status">
          {CostWords.shortBy(quote, balance)}{" "}
          <Link href="/buy" className="font-bold text-primary-text underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            Buy credits
          </Link>
        </span>
      ) : null}
    </span>
  );
}
