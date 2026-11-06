"use client";

import { CoinsIcon } from "lucide-react";
import Link from "next/link";

import { useCredits } from "@/components/credits/credits-provider";
import { buttonVariants } from "@/components/ui/button";
import { WalletWords } from "@/lib/credits/wallet-words";

/** The header's balance. It links to the wallet; a dot says some credits are about to run out. */
export function BalanceChip() {
  const { balance } = useCredits();
  if (!balance) return null;
  const parts = [`You have ${WalletWords.credits(balance.balance)}`];
  if (balance.reserved > 0) parts.push(WalletWords.reserved(balance.reserved));
  if (balance.notices > 0) parts.push("some are about to run out");
  return (
    <Link href="/wallet" aria-label={`${parts.join(", ")}. Open your credits`} title={parts.join(", ")} className={buttonVariants({ variant: "ghost", className: "relative gap-1.5 px-2.5" })} data-testid="balance-chip">
      <CoinsIcon aria-hidden="true" className="text-marigold-text" />
      <span className="font-mono text-sm font-bold tabular-nums">{balance.balance}</span>
      {balance.notices > 0 ? <span aria-hidden="true" className="absolute top-1.5 right-1 size-2 rounded-full bg-marigold" /> : null}
    </Link>
  );
}
