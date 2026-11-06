"use client";

import { useCallback, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import type { BuyRequest } from "@/lib/payments/types";
import { checkoutAdapters } from "@/lib/payments/checkout-adapters";
import { PaymentWords } from "@/lib/payments/payment-words";
import { paymentsApi } from "@/lib/payments/payments-api";

/**
 * Starts a payment and takes the learner to pay. One press is one order: while it is working the buttons are off, and a
 * second try of the same purchase reuses its idempotency key, so a dropped answer or a double click cannot make two. A new
 * purchase gets a new key. Nothing is granted here: the learner is sent to the provider and comes back to a page that asks.
 */
export function useBuy() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const keys = useRef(new Map<string, string>());

  const buy = useCallback(async (label: string, request: BuyRequest) => {
    const same = JSON.stringify(request);
    const key = keys.current.get(same) ?? crypto.randomUUID();
    keys.current.set(same, key);
    setBusy(label);
    setError(null);
    try {
      const order = await paymentsApi.createOrder(request, key);
      await checkoutAdapters.begin(order.checkout, `/buy/return?order=${order.id}`);
      // The browser is on its way to the provider; the buttons stay off until it leaves.
    } catch (err) {
      if (err instanceof ApiError && err.status < 500 && err.code !== "too_many_pending") keys.current.delete(same);
      setError(PaymentWords.refusal(err));
      setBusy(null);
    }
  }, []);

  return { busy, error, buy, clearError: () => setError(null) };
}
