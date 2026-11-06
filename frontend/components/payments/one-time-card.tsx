"use client";

import { CoinsIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BuyState, PlanWords } from "@/lib/credits/plan-words";
import type { OneTimeRules } from "@/lib/credits/types";
import { OneTimeChoices } from "@/lib/payments/buy-choices";
import { cn } from "@/lib/utils";

type Props = { rules: OneTimeRules; open: boolean; busy: boolean; onBuy: (credits: number) => void };

/** Credits by the amount: a few chips for the usual amounts and a box for any other, with the price in rupees as it changes. */
export function OneTimeCard({ rules, open, busy, onBuy }: Props) {
  const [picked, setPicked] = useState<number | null>(100);
  const [custom, setCustom] = useState("");
  const amount = OneTimeChoices.amount(picked, custom, rules);
  const chosen = amount && "credits" in amount ? amount : null;
  return (
    <Card data-testid="plan-one_time">
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          {PlanWords.rupees(rules.price_paise_per_credit)} a credit, from {rules.min_credits} to {rules.max_credits} credits. They last {PlanWords.valid(rules.valid_days)}.
        </p>
        <div role="group" aria-label="Popular amounts" className="flex flex-wrap gap-2">
          {OneTimeChoices.presets(rules).map((credits) => (
            <button
              key={credits}
              type="button"
              aria-pressed={picked === credits}
              disabled={busy}
              data-testid={`chip-${credits}`}
              onClick={() => {
                setPicked(credits);
                setCustom("");
              }}
              className={cn(
                "rounded-full border-2 px-4 py-1.5 font-mono text-sm font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
                picked === credits ? "border-primary bg-primary-soft text-primary-text" : "border-border bg-card hover:bg-muted",
              )}
            >
              {credits}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="amount">Or pick your own amount</Label>
          <Input
            id="amount"
            inputMode="numeric"
            autoComplete="off"
            value={custom}
            disabled={busy}
            onChange={(event) => {
              setCustom(event.target.value);
              setPicked(null);
            }}
            aria-invalid={amount !== null && "message" in amount}
            aria-describedby="amount-help"
            className="max-w-48"
          />
          <p id="amount-help" className="min-h-5 text-sm" role="status" data-testid="amount-help">
            {chosen ? OneTimeChoices.total(chosen.credits, rules) : amount && "message" in amount ? amount.message : ""}
          </p>
        </div>
        {open ? (
          <Button disabled={busy || !chosen} className="w-fit gap-1.5" onClick={() => chosen && onBuy(chosen.credits)} data-testid="buy-one_time">
            <CoinsIcon aria-hidden="true" /> {busy ? "Taking you to pay…" : chosen ? `Buy for ${PlanWords.rupees(chosen.paise)}` : "Pick an amount"}
          </Button>
        ) : (
          <Button disabled className="w-fit gap-1.5">
            <CoinsIcon aria-hidden="true" /> {BuyState.CLOSED_TEXT}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
