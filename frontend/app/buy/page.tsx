"use client";

import { useState } from "react";

import { LoadFailure, PageFrame } from "@/components/credits/page-frame";
import { useLoaded } from "@/components/credits/use-loaded";
import { GatewayPicker } from "@/components/payments/gateway-picker";
import { OneTimeCard } from "@/components/payments/one-time-card";
import { PlanCard } from "@/components/payments/plan-card";
import { useBuy } from "@/components/payments/use-buy";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { creditsApi } from "@/lib/credits/credits-api";
import { BuyState, PlanWords } from "@/lib/credits/plan-words";
import { GatewayChoices } from "@/lib/payments/gateway-choices";
import { paymentsApi } from "@/lib/payments/payments-api";

export default function BuyPage() {
  const plans = useLoaded(() => creditsApi.plans(), "We couldn't load the plans.");
  const ways = useLoaded(() => paymentsApi.gateways(), "We couldn't load the ways to pay.");
  const { busy, error, buy } = useBuy();
  const [picked, setPicked] = useState<string | null>(null);

  const data = plans.data;
  const gateways = ways.data;
  const open = gateways ? GatewayChoices.open(gateways) : false;
  const gateway = gateways ? (picked ?? GatewayChoices.initial(gateways) ?? "") : "";
  const chosen = gateways ? GatewayChoices.request(gateways, gateway) : undefined;
  const loadError = plans.error ?? ways.error;

  return (
    <PageFrame eyebrow="Credits" title="Get more credits">
      {loadError && <LoadFailure message={loadError} />}
      {(!data || !gateways) && !loadError && <Skeleton className="h-64 rounded-[22px]" aria-busy="true" aria-label="Loading the plans" />}

      {data && gateways && (
        <>
          {!open && (
            <p className="rounded-xl bg-muted px-3 py-2 text-sm font-semibold" role="status" data-testid="buy-closed">
              {BuyState.CLOSED_TEXT}. {BuyState.CLOSED_HELP}
            </p>
          )}
          {error && (
            <Alert variant="destructive" role="alert" data-testid="buy-error">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

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

          {open && <GatewayPicker gateways={gateways} value={gateway} onChange={setPicked} disabled={busy !== null} />}

          {data.one_time && (
            <section aria-labelledby="own" className="flex flex-col gap-3">
              <h2 id="own" className="font-heading text-xl font-semibold">
                Credits
              </h2>
              <OneTimeCard
                rules={data.one_time}
                open={open}
                busy={busy !== null}
                onBuy={(credits) => void buy("one_time", { plan: "one_time", credits, gateway: chosen })}
              />
            </section>
          )}

          <section aria-labelledby="plans" className="flex flex-col gap-3">
            <h2 id="plans" className="font-heading text-xl font-semibold">
              Plans
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2" data-testid="buy-plans">
              {PlanWords.recurring(data).map((plan) => (
                <li key={plan.key}>
                  <PlanCard plan={plan} open={open} busy={busy !== null} onBuy={(quantity) => void buy(plan.key, { plan: plan.key, quantity, gateway: chosen })} />
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </PageFrame>
  );
}
