"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ErrorState } from "@/components/console/error-state";
import { HealthPill } from "@/components/console/health-pill";
import { KpiTile } from "@/components/console/kpi-tile";
import { AttentionCard } from "@/components/console/overview/attention-card";
import { FunnelCard } from "@/components/console/overview/funnel-card";
import { SlowestStepsCard } from "@/components/console/overview/slowest-steps-card";
import { SpendCard } from "@/components/console/overview/spend-chart";
import { PageHeader } from "@/components/console/page-header";
import { RangeToggle } from "@/components/console/range-toggle";
import { CardSkeleton, KpiRowSkeleton } from "@/components/console/skeletons";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { HealthPills, OverviewKpis } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import { consoleQueries } from "@/lib/console-queries";
import { ConsoleUrl } from "@/lib/console-url";
import type { ConsoleRange } from "@/lib/types";

const RANGES: ConsoleRange[] = ["today", "7d", "30d"];
const RANGE_OPTIONS = RANGES.map((value) => ({ value, label: ConsoleFormat.rangeLabel(value) }));

/** The Overview page. The range lives in the address; health and attention are polled every minute. */
export function OverviewView() {
  const router = useRouter();
  const pathname = usePathname();
  const range = ConsoleUrl.overviewRange(useSearchParams());
  const { data, error, isPending, isPlaceholderData, refetch } = useConsoleQuery({ ...consoleQueries.overview(range), placeholderData: keepPreviousData });

  const toggle = (
    <RangeToggle options={RANGE_OPTIONS} value={range} onChange={(next) => router.replace(`${pathname}${ConsoleUrl.overviewQuery(next)}`, { scroll: false })} />
  );
  const header = (health?: React.ReactNode) => (
    <PageHeader
      title="Overview"
      description="How Socra is doing."
      actions={
        <>
          {health}
          {toggle}
        </>
      }
    />
  );

  if (error && !data) return <>{header()}<ErrorState message="The overview could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !data) {
    return (
      <div aria-busy="true">
        {header()}
        <KpiRowSkeleton />
        <div className="mt-4 grid grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)] gap-4 max-[900px]:grid-cols-1">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }

  return (
    <div aria-busy={isPlaceholderData} className={isPlaceholderData ? "opacity-70 motion-safe:transition-opacity" : undefined}>
      {header(
        <ul aria-label="System health" className="flex flex-wrap gap-2">
          {HealthPills.of(data.health).map(({ key, ...pill }) => (
            <li key={key}>
              <HealthPill {...pill} />
            </li>
          ))}
        </ul>,
      )}

      <div className="grid grid-cols-4 gap-4 max-[1180px]:grid-cols-2 max-[560px]:grid-cols-1">
        {OverviewKpis.of(data).map((kpi) => (
          <KpiTile key={kpi.key} data={kpi} />
        ))}
      </div>

      <div className="mt-4 grid grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)] gap-4 max-[900px]:grid-cols-1">
        <SpendCard daily={data.daily_spend} />
        <FunnelCard funnel={data.funnel} range={data.range} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        <AttentionCard items={data.attention} />
        <SlowestStepsCard steps={data.slowest_steps} range={data.range} />
      </div>
    </div>
  );
}
