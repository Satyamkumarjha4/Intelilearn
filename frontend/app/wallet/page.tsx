"use client";

import { AlarmClockIcon, CoinsIcon, FlameIcon, HistoryIcon, ShoppingBagIcon } from "lucide-react";
import Link from "next/link";

import { LoadFailure, PageFrame } from "@/components/credits/page-frame";
import { useLoaded } from "@/components/credits/use-loaded";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { creditsApi } from "@/lib/credits/credits-api";
import { WalletWords } from "@/lib/credits/wallet-words";

export default function WalletPage() {
  const wallet = useLoaded(() => creditsApi.wallet(), "We couldn't load your credits.");
  const notices = useLoaded(() => creditsApi.notices(), "We couldn't load your reminders.");
  const now = new Date();

  return (
    <PageFrame eyebrow="Your credits" title="Credits">
      {wallet.error && <LoadFailure message={wallet.error} />}
      {!wallet.data && !wallet.error && <Skeleton className="h-40 rounded-[22px]" aria-busy="true" aria-label="Loading your credits" />}

      {wallet.data && (
        <>
          <Card>
            <CardContent className="flex flex-col gap-3">
              <p className="text-sm font-bold text-muted-foreground">You can use</p>
              <p className="flex items-center gap-2 font-heading text-5xl font-semibold" data-testid="wallet-balance" data-balance={wallet.data.balance}>
                <CoinsIcon className="size-9 text-marigold-text" aria-hidden="true" /> {wallet.data.balance}
                <span className="text-lg font-semibold text-muted-foreground">{wallet.data.balance === 1 ? "credit" : "credits"}</span>
              </p>
              {wallet.data.reserved > 0 && (
                <p className="text-sm text-muted-foreground" data-testid="wallet-reserved">
                  {WalletWords.reserved(wallet.data.reserved)}.
                </p>
              )}
              {wallet.data.exempt && <p className="text-sm font-bold text-success-text">Lessons and quizzes are free for you.</p>}
              <div className="flex flex-wrap gap-2 pt-1">
                <Link href="/buy" className={buttonVariants({ variant: "marigold", className: "gap-1.5" })}>
                  <ShoppingBagIcon aria-hidden="true" /> Get more credits
                </Link>
                <Link href="/wallet/history" className={buttonVariants({ variant: "outline", className: "gap-1.5" })}>
                  <HistoryIcon aria-hidden="true" /> History
                </Link>
                <Link href="/streak" className={buttonVariants({ variant: "outline", className: "gap-1.5" })}>
                  <FlameIcon aria-hidden="true" /> Your streak
                </Link>
              </div>
            </CardContent>
          </Card>

          {notices.data && notices.data.notices.length > 0 && (
            <section aria-label="Credits running out" className="flex flex-col gap-2" data-testid="wallet-notices">
              {notices.data.notices.map((notice) => (
                <p key={notice.id} className="flex items-start gap-2 rounded-xl bg-marigold-soft px-3 py-2 text-sm font-semibold text-marigold-text">
                  <AlarmClockIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> {notice.text}
                </p>
              ))}
            </section>
          )}

          <section aria-labelledby="where-from" className="flex flex-col gap-3">
            <h2 id="where-from" className="font-heading text-xl font-semibold">
              What you have
            </h2>
            <p className="text-sm text-muted-foreground">Credits that run out first are used first.</p>
            {wallet.data.buckets.length === 0 ? (
              <p className="rounded-xl border-2 border-dashed p-4 text-center text-muted-foreground">{WalletWords.NONE}</p>
            ) : (
              <ul className="flex flex-col gap-2" data-testid="wallet-groups">
                {WalletWords.groups(wallet.data.buckets, now).map((group) => (
                  <li key={group.key}>
                    <Card size="sm">
                      <CardContent className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-bold">{group.label}</p>
                          <p className="text-sm text-muted-foreground">{group.expiry}</p>
                        </div>
                        <p className="font-mono text-lg font-bold tabular-nums">{group.remaining}</p>
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </PageFrame>
  );
}
