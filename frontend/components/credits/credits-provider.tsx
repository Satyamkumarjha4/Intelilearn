"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { apiClient } from "@/lib/api";
import { creditsApi } from "@/lib/credits/credits-api";
import { QuoteClient, quoteClient } from "@/lib/credits/quote-client";
import type { Balance } from "@/lib/credits/types";

type CreditsState = {
  /** What the header shows; null until the first answer, and for someone who is signed out. */
  balance: Balance | null;
  /** Ask again now (after something that spends or earns). */
  refresh: () => Promise<void>;
  /** Prices, remembered for a little while. */
  quotes: QuoteClient;
};

const CreditsContext = createContext<CreditsState>({ balance: null, refresh: async () => {}, quotes: quoteClient });

export function useCredits(): CreditsState {
  return useContext(CreditsContext);
}

const POLL_MS = 60_000;
const NOT_ENOUGH = "not-enough-credits";

/**
 * Keeps the balance for the header and tells a learner what to do when something they started needed more credits than
 * they have. Many screens start paid work and each already writes its own sentence for a refusal; this adds what they
 * share, a way to buy, so no screen has to remember to.
 */
export function CreditsProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [balance, setBalance] = useState<Balance | null>(null);
  const signedIn = Boolean(user);

  const refresh = useCallback(async () => {
    if (!signedIn) return;
    try {
      setBalance(await creditsApi.balance());
    } catch {
      // the chip simply keeps what it had; nothing else depends on this call
    }
  }, [signedIn]);

  // Moving to another page is the usual moment something was spent or earned.
  useEffect(() => {
    if (!signedIn) return;
    let active = true;
    creditsApi
      .balance()
      .then((answer) => active && setBalance(answer))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [signedIn, pathname]);

  useEffect(() => {
    if (!signedIn) return;
    const again = () => document.visibilityState === "visible" && void refresh();
    const timer = window.setInterval(again, POLL_MS);
    window.addEventListener("focus", again);
    document.addEventListener("visibilitychange", again);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", again);
      document.removeEventListener("visibilitychange", again);
    };
  }, [signedIn, refresh]);

  useEffect(
    () =>
      apiClient.observe((error) => {
        if (error.status !== 402 || error.code !== "insufficient_credits") return;
        void refresh();
        toast.error("Not enough credits", {
          id: NOT_ENOUGH,
          description: "Buy more to carry on. What you've done so far is kept.",
          action: { label: "Buy credits", onClick: () => router.push("/buy") },
        });
      }),
    [refresh, router],
  );

  const value = useMemo<CreditsState>(() => ({ balance: signedIn ? balance : null, refresh, quotes: quoteClient }), [signedIn, balance, refresh]);
  return <CreditsContext.Provider value={value}>{children}</CreditsContext.Provider>;
}
