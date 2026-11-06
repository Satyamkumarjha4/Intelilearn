"use client";

import { MinusIcon, PlusIcon, ShoppingBagIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { BuyState, PlanWords } from "@/lib/credits/plan-words";
import type { Plan } from "@/lib/credits/types";
import { PlanQuantity } from "@/lib/payments/buy-choices";

type Props = { plan: Plan; open: boolean; busy: boolean; onBuy: (quantity: number) => void };

/** One plan to buy. A plan sold by the week has a small stepper for how many; the total follows it. */
export function PlanCard({ plan, open, busy, onBuy }: Props) {
  const [quantity, setQuantity] = useState(1);
  const total = PlanQuantity.total(plan, quantity);
  const n = PlanQuantity.clamp(plan, quantity);
  return (
    <Card className="h-full" data-testid={`plan-${plan.key}`}>
      <CardContent className="flex h-full flex-col gap-2">
        <h3 className="font-heading text-lg font-semibold">{plan.name}</h3>
        <p className="font-heading text-2xl font-semibold">{PlanWords.price(plan)}</p>
        <p className="flex-1 text-sm text-muted-foreground">{PlanWords.gives(plan)}</p>
        {PlanQuantity.canChoose(plan) && (
          <div className="flex items-center gap-2" role="group" aria-label={`How many weeks of ${plan.name}`}>
            <Button type="button" variant="outline" size="icon" aria-label="One week fewer" disabled={!open || busy || n <= 1} onClick={() => setQuantity(n - 1)}>
              <MinusIcon aria-hidden="true" />
            </Button>
            <span className="min-w-20 text-center font-bold" aria-live="polite" data-testid={`plan-${plan.key}-weeks`}>
              {PlanQuantity.words(plan, n)}
            </span>
            <Button type="button" variant="outline" size="icon" aria-label="One week more" disabled={!open || busy || n >= plan.max_quantity} onClick={() => setQuantity(n + 1)}>
              <PlusIcon aria-hidden="true" />
            </Button>
          </div>
        )}
        {open ? (
          <Button disabled={busy} className="gap-1.5" onClick={() => onBuy(n)} data-testid={`buy-${plan.key}`}>
            <ShoppingBagIcon aria-hidden="true" /> {busy ? "Taking you to pay…" : `Buy for ${PlanWords.rupees(total.paise)}`}
          </Button>
        ) : (
          <Button disabled className="gap-1.5" aria-label={`${BuyState.CLOSED_TEXT}: ${plan.name}`}>
            <ShoppingBagIcon aria-hidden="true" /> {BuyState.CLOSED_TEXT}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
