"use client";

import { CoinsIcon, ShoppingBagIcon } from "lucide-react";
import { useState } from "react";

import { LoadFailure, PageFrame } from "@/components/credits/page-frame";
import { useLoaded } from "@/components/credits/use-loaded";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { creditsApi } from "@/lib/credits/credits-api";
import { BuyState, PlanWords } from "@/lib/credits/plan-words";

export default function BuyPage() {
  const plans = useLoaded(() => creditsApi.plans(), "We couldn't load the plans.");
  const [amount, setAmount] = useState("");
  const data = plans.data;
  const check = data?.one_time && amount.trim() ? PlanWords.check(amount, data.one_time) : null;

  return (
    <PageFrame eyebrow="Credits" title="Get more credits">
      {plans.error && <LoadFailure message={plans.error} />}
      {!data && !plans.error && <Skeleton className="h-64 rounded-[22px]" aria-busy="true" aria-label="Loading the plans" />}

      {data && (
        <>
          <p className="rounded-xl bg-muted px-3 py-2 text-sm font-semibold" role="status" data-testid="buy-closed">
            {BuyState.CLOSED_TEXT}. {BuyState.CLOSED_HELP}
          </p>

          {data.periods.length > 0 && (
            <section aria-labelledby="yours" className="flex flex-col gap-2">
              <h2 id="yours" className="font-heading text-xl font-semibold">
                Your plans
              </h2>
              <ul className="flex flex-col gap-2" data-testid="buy-periods">
                {data.periods.map((period) => (
                  <li key={`${period.plan}-${period.starts_at}`} className="flex flex-wrap items-center gap-2 rounded-xl border-2 px-3 py-2">
                    <Badge variant={period.status === "active" ? "primary" : "marigold"}>{period.status === "active" ? "Running" : "Waiting"}</Badge>
                    <span className="min-w-0 flex-1 text-sm">{PlanWords.period(period)}</span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">{PlanWords.queue(data.queue)}</p>
            </section>
          )}

          <section aria-labelledby="plans" className="flex flex-col gap-3">
            <h2 id="plans" className="font-heading text-xl font-semibold">
              Plans
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2" data-testid="buy-plans">
              {PlanWords.recurring(data).map((plan) => (
                <li key={plan.key}>
                  <Card className="h-full">
                    <CardContent className="flex h-full flex-col gap-2">
                      <h3 className="font-heading text-lg font-semibold">{plan.name}</h3>
                      <p className="font-heading text-2xl font-semibold">{PlanWords.price(plan)}</p>
                      <p className="flex-1 text-sm text-muted-foreground">{PlanWords.gives(plan)}</p>
                      <Button disabled className="gap-1.5" aria-label={`${BuyState.CLOSED_TEXT}: ${plan.name}`}>
                        <ShoppingBagIcon aria-hidden="true" /> {BuyState.CLOSED_TEXT}
                      </Button>
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
          </section>

          {data.one_time && (
            <section aria-labelledby="own" className="flex flex-col gap-3">
              <h2 id="own" className="font-heading text-xl font-semibold">
                Pick your own amount
              </h2>
              <Card>
                <CardContent className="flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground">
                    {PlanWords.rupees(data.one_time.price_paise_per_credit)} a credit, from {data.one_time.min_credits} to {data.one_time.max_credits} credits. They last{" "}
                    {PlanWords.valid(data.one_time.valid_days)}.
                  </p>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="amount">How many credits?</Label>
                    <Input
                      id="amount"
                      inputMode="numeric"
                      autoComplete="off"
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
                      aria-invalid={check?.ok === false}
                      aria-describedby="amount-help"
                      className="max-w-48"
                    />
                    <p id="amount-help" className="text-sm" role="status" data-testid="amount-help">
                      {check === null ? " " : check.ok ? `${check.credits} credits: ${PlanWords.rupees(check.paise)}` : check.message}
                    </p>
                  </div>
                  <Button disabled className="w-fit gap-1.5">
                    <CoinsIcon aria-hidden="true" /> {BuyState.CLOSED_TEXT}
                  </Button>
                </CardContent>
              </Card>
            </section>
          )}
        </>
      )}
    </PageFrame>
  );
}
