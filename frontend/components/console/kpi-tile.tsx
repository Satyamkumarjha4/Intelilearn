import { DeltaChip } from "@/components/console/delta-chip";
import { Meter } from "@/components/console/meter";
import { Sparkline } from "@/components/console/sparkline";
import type { KpiData } from "@/lib/console-charts";
import { cn } from "@/lib/utils";

/** One headline number: what it is, the figure, a change or a note, and a line or a meter under it. */
/** `small` is for a value that is words, not a number ("School · Class 10"). */
export function KpiTile({ data }: { data: Pick<KpiData, "label" | "value" | "detail"> & Partial<KpiData> & { small?: boolean } }) {
  return (
    <section aria-label={data.label} className="grid content-start gap-1.5 rounded-2xl border bg-card p-4 shadow-card">
      <h2 className="font-sans text-[12.5px] font-extrabold text-muted-foreground">{data.label}</h2>
      <p className={cn("font-heading leading-[1.05] font-semibold tabular-nums", data.small ? "text-[22px]" : "text-[30px]")}>
        {data.value}
        {data.suffix ? <small className="ml-1.5 font-sans text-base font-semibold text-muted-foreground">{data.suffix}</small> : null}
      </p>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] font-bold text-muted-foreground">
        {data.delta ? <DeltaChip label={data.delta.label} tone={data.delta.tone} /> : null}
        <span>{data.detail}</span>
      </p>
      {data.meter ? <Meter {...data.meter} /> : null}
      {data.spark ? <Sparkline values={data.spark.values} label={data.spark.label} /> : null}
    </section>
  );
}
