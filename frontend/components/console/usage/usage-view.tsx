"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { DownloadIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { ErrorState } from "@/components/console/error-state";
import { KpiTile } from "@/components/console/kpi-tile";
import { PageHeader } from "@/components/console/page-header";
import { CardSkeleton, KpiRowSkeleton } from "@/components/console/skeletons";
import { LatencyCard } from "@/components/console/usage/latency-card";
import { OutcomeCard } from "@/components/console/usage/outcome-card";
import { StepsCard } from "@/components/console/usage/steps-card";
import { UsageFilterBar } from "@/components/console/usage/usage-filters";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { buttonVariants } from "@/components/ui/button";
import { consoleApi } from "@/lib/console-api";
import { UsageKpis } from "@/lib/console-charts";
import { consoleQueries } from "@/lib/console-queries";
import { ConsoleUrl } from "@/lib/console-url";
import type { UsageFilters } from "@/lib/types";

/** The Usage & cost page. Every filter lives in the address, so a view can be shared and survives a reload. */
export function UsageView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const filters = useMemo(() => ConsoleUrl.usageFilters(params), [params]);

  const usage = useConsoleQuery({ ...consoleQueries.usage(filters), placeholderData: keepPreviousData });
  // The choices in the drop-downs are a nicety: if they cannot be loaded the page still works with what the address says.
  const providers = useConsoleQuery(consoleQueries.providers()).data ?? [];
  const models = useConsoleQuery(consoleQueries.models()).data ?? [];
  const steps = useConsoleQuery(consoleQueries.steps()).data ?? [];

  const go = (next: UsageFilters) => router.replace(`${pathname}${ConsoleUrl.usageQuery(next)}`, { scroll: false });
  const { data, error, isPending, isPlaceholderData, refetch } = usage;

  const header = (
    <>
      <PageHeader
        title="Usage & cost"
        description="Every model call Socra makes."
        actions={
          <a href={consoleApi.usageExportUrl(filters)} download className={buttonVariants({ variant: "outline" })}>
            <DownloadIcon aria-hidden="true" /> Export CSV
          </a>
        }
      />
      <UsageFilterBar filters={filters} providers={providers} models={models} steps={steps} onChange={go} />
    </>
  );

  if (error && !data) return <>{header}<ErrorState message="The usage figures could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !data) {
    return (
      <div aria-busy="true">
        {header}
        <KpiRowSkeleton />
        <div className="mt-4 grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }

  return (
    <div aria-busy={isPlaceholderData} className={isPlaceholderData ? "opacity-70 motion-safe:transition-opacity" : undefined}>
      {header}
      <div className="grid grid-cols-4 gap-4 max-[1180px]:grid-cols-2 max-[560px]:grid-cols-1">
        {UsageKpis.of(data).map((kpi) => (
          <KpiTile key={kpi.key} data={kpi} />
        ))}
      </div>
      <div className="mt-4 grid grid-cols-2 items-start gap-4 max-[900px]:grid-cols-1">
        <LatencyCard byModel={data.by_model} />
        <OutcomeCard usage={data} />
      </div>
      <StepsCard byNode={data.by_node} />
    </div>
  );
}
