"use client";

import { useEffect, useState } from "react";

import { useCredits } from "@/components/credits/credits-provider";
import type { CostAsk } from "@/lib/credits/cost-sizes";
import { QuoteClient } from "@/lib/credits/quote-client";
import type { Quote } from "@/lib/credits/types";

/**
 * The price of what a screen is about to start, from the server. `undefined` while it is being asked, `null` when it
 * cannot be had (the label then says nothing and the action is not blocked: the server decides when it is clicked).
 * Ask with `retryLessonId` for the Retry on a failed lesson.
 */
export function useQuote(ask: CostAsk | null, retryLessonId?: string): Quote | null | undefined {
  const { quotes } = useCredits();
  const key = retryLessonId ? `retry|${retryLessonId}` : ask ? QuoteClient.key(ask) : null;
  const [answer, setAnswer] = useState<{ key: string; quote: Quote | null } | null>(null);

  useEffect(() => {
    if (!key) return;
    let active = true;
    const pending = retryLessonId ? quotes.retry(retryLessonId) : quotes.quote(ask!);
    void pending.then((quote) => active && setAnswer({ key, quote }));
    return () => {
      active = false;
    };
    // `ask` is rebuilt on every render; `key` says when it is a different question
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, quotes, retryLessonId]);

  if (!key) return null;
  return answer?.key === key ? answer.quote : undefined;
}
