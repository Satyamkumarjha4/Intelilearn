"use client";

import { ErrorState } from "@/components/console/error-state";
import { KpiTile } from "@/components/console/kpi-tile";
import { KpiRowSkeleton } from "@/components/console/skeletons";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { ConsolePaymentWords } from "@/lib/console-credits/payment-words";
import { creditQueries } from "@/lib/console-credits/queries";
import type { UsageFilters } from "@/lib/types";

/** Revenue beside model cost, both in rupees, for the page's range, with the dollar rate that made the cost (T31). */
export function RevenueCard({ filters }: { filters: UsageFilters }) {
  const { data, error, isPending, refetch } = useConsoleQuery(creditQueries.revenue(filters));
  if (error && !data) return <ErrorState message="The revenue figures could not be loaded." onRetry={() => void refetch()} />;
  if (isPending || !data) return <KpiRowSkeleton count={4} />;
  const rupees = ConsolePaymentWords.rupees;
  return (
    <section aria-label="Revenue and model cost" className="grid gap-2">
      <div className="grid grid-cols-4 gap-4 max-[1180px]:grid-cols-2 max-[560px]:grid-cols-1">
        <KpiTile data={{ label: "Paid", value: rupees(data.paid), detail: `${data.orders} ${data.orders === 1 ? "order" : "orders"} in the range` }} />
        <KpiTile data={{ label: "Refunded", value: rupees(data.refunded), detail: "taken back by refunds and disputes" }} />
        <KpiTile data={{ label: "Net revenue", value: rupees(data.net), detail: "paid less refunded" }} />
        <KpiTile data={{ label: "Model cost", value: rupees(data.model_cost), detail: `${rupees(data.after_model_cost)} left after it` }} />
      </div>
      <p className="text-[12.5px] font-semibold text-muted-foreground">{ConsolePaymentWords.rate(data)}</p>
    </section>
  );
}
