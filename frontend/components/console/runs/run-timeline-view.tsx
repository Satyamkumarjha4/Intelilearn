import { RunTimeline, type Lane } from "@/lib/run-timeline";
import { RunText } from "@/lib/run-text";
import type { TimelineState, TimelineStep } from "@/lib/types";
import { cn } from "@/lib/utils";

const BAR: Record<TimelineState, string> = {
  ran: "bg-primary",
  retried: "bg-marigold",
  failed: "bg-destructive",
  waiting: "border border-border",
};
const HATCH = "repeating-linear-gradient(135deg, var(--border) 0 4px, transparent 4px 8px)";
const TIP_SIDE = { start: "left-0", center: "left-1/2 -translate-x-1/2", end: "right-0" } as const;

const LEGEND: { state: TimelineState; label: string }[] = [
  { state: "ran", label: "Ran" },
  { state: "retried", label: "Retried" },
  { state: "failed", label: "Failed" },
  { state: "waiting", label: "Waiting for learner" },
];

function Swatch({ state }: { state: TimelineState }) {
  return (
    <i
      aria-hidden="true"
      className={cn("inline-block size-2.5 rounded-[3px]", BAR[state])}
      style={state === "waiting" ? { background: HATCH } : undefined}
    />
  );
}

function LaneRow({ lane }: { lane: Lane }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)_44px] items-center gap-2 text-xs min-[560px]:grid-cols-[132px_minmax(0,1fr)_46px]">
      <span className="truncate font-mono text-[11.5px] text-muted-foreground" title={lane.node}>
        {lane.node}
      </span>
      {/* The lane is the thing that takes focus, so the hover text is there for the keyboard too. */}
      <div
        role="img"
        aria-label={lane.label}
        tabIndex={0}
        className="group relative h-4 rounded bg-muted outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {lane.bar && (
          <span
            className={cn("absolute inset-y-0.5 rounded", BAR[lane.state])}
            style={{
              left: `${lane.bar.left}%`,
              width: `${lane.bar.width}%`,
              ...(lane.state === "waiting" ? { background: HATCH } : {}),
            }}
          />
        )}
        <div
          role="presentation"
          className={cn(
            "pointer-events-none absolute bottom-full z-10 mb-1.5 hidden w-max min-w-40 max-w-64 rounded-lg border bg-popover p-2 text-xs text-popover-foreground shadow-card group-hover:block group-focus-visible:block",
            TIP_SIDE[lane.tipAlign],
          )}
        >
          <b className="mb-1 block break-all font-mono">{lane.tip.title}</b>
          {lane.tip.rows.map(([name, value]) => (
            <div key={name} className="flex justify-between gap-3">
              <span className="text-muted-foreground">{name}</span>
              <span className="text-right font-mono">{value}</span>
            </div>
          ))}
        </div>
      </div>
      <span className="text-right font-mono text-[11.5px] text-muted-foreground">{lane.durationText}</span>
    </div>
  );
}

/** The run's steps as lanes under phase headings, each bar placed by when it started and sized by how long it took. */
export function RunTimelineView({ steps, runDurationS }: { steps: TimelineStep[]; runDurationS: number | null }) {
  const view = RunTimeline.layout(steps, runDurationS);
  return (
    <div>
      {view.phases.length === 0 ? (
        <p className="text-sm text-muted-foreground">No steps have started yet.</p>
      ) : (
        <div className="grid gap-1">
          {view.phases.map((phase) => (
            <div key={phase.phase} className="grid gap-1">
              <h4 className="mt-2 font-sans text-[11px] font-extrabold tracking-wider text-muted-foreground uppercase first:mt-0">{phase.label}</h4>
              {phase.lanes.map((lane) => (
                <LaneRow key={lane.key} lane={lane} />
              ))}
            </div>
          ))}
        </div>
      )}
      <p className="mt-2 text-right font-mono text-[11px] text-muted-foreground">Whole bar: {RunText.duration(view.totalS)}</p>
      <ul className="mt-2 flex flex-wrap gap-x-3.5 gap-y-1 text-xs font-bold text-muted-foreground" aria-label="Key">
        {LEGEND.map((item) => (
          <li key={item.state} className="inline-flex items-center gap-1.5">
            <Swatch state={item.state} />
            {item.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
