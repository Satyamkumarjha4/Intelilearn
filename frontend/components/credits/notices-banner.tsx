"use client";

import { AlarmClockIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useCredits } from "@/components/credits/credits-provider";
import { Button } from "@/components/ui/button";
import { creditsApi } from "@/lib/credits/credits-api";
import { NoticeDismissals } from "@/lib/credits/notice-dismissals";
import type { Notice } from "@/lib/credits/types";

const SHOWN = 2;

/**
 * Credits that are about to run out, under the header. "Not now" hides a notice for the rest of the day in this browser
 * (it comes back tomorrow, because the credits are still about to run out). Only asked for when the balance says there is
 * something to tell.
 */
export function NoticesBanner() {
  const { balance } = useCredits();
  const dismissals = useMemo(() => new NoticeDismissals(), []);
  const [loaded, setLoaded] = useState<{ count: number; notices: Notice[] } | null>(null);
  const [, setPutAway] = useState(0);
  const count = balance?.notices ?? 0;

  useEffect(() => {
    if (count === 0) return;
    let active = true;
    creditsApi
      .notices()
      .then((answer) => active && setLoaded({ count, notices: answer.notices }))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [count]);

  const visible = count > 0 && loaded?.count === count ? dismissals.visible(loaded.notices) : [];
  if (visible.length === 0) return null;
  const shown = visible.slice(0, SHOWN);

  return (
    <section aria-label="Credits running out" className="border-b bg-marigold-soft text-marigold-text" data-testid="notices-banner">
      <ul className="mx-auto flex w-full max-w-5xl flex-col gap-1 px-4 py-2">
        {shown.map((notice) => (
          <li key={notice.id} className="flex items-start gap-2 text-sm font-semibold">
            <AlarmClockIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p className="min-w-0 flex-1" data-testid="notice-text">
              {notice.text}{" "}
              <Link href="/wallet" className="underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                See your credits
              </Link>
            </p>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Hide this for today"
              onClick={() => {
                dismissals.dismiss(notice.id);
                setPutAway((n) => n + 1);
              }}
            >
              <XIcon aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
