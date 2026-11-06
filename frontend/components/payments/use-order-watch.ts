"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { OrderWatch, type Phase } from "@/lib/payments/order-watch";
import { paymentsApi } from "@/lib/payments/payments-api";
import type { Order } from "@/lib/payments/types";

/** Asks the server about an order until it is settled. It decides nothing itself: the phase is `OrderWatch`'s reading of
 *  what the server said. `missing` is a 404 (not this learner's, or not there). */
export function useOrderWatch(orderId: string | null) {
  const [order, setOrder] = useState<Order | null>(null);
  const [phase, setPhase] = useState<Phase>("waiting");
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!orderId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const started = Date.now();
    const ask = async () => {
      let found: Order | null = null;
      let failed = false;
      try {
        found = await paymentsApi.order(orderId);
        if (!active) return;
        setOrder(found);
      } catch (err) {
        if (!active) return;
        if (err instanceof ApiError && err.status === 404) return setMissing(true);
        failed = true;
      }
      const step = OrderWatch.next(found, Date.now() - started, failed);
      setPhase(step.phase);
      if (step.pollIn !== null) timer = setTimeout(() => void ask(), step.pollIn);
    };
    void ask();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [orderId]);

  return { order, phase, missing };
}
