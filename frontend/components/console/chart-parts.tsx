import { RoundedRect, type RoundedCorners } from "@/lib/chart-shapes";
import type { TooltipData } from "@/lib/console-charts";

/** The mono, small tick labels every chart uses. */
export const TICK = { fontFamily: "var(--font-mono)", fontSize: 11, fill: "var(--muted-foreground)" } as const;
/** The recessive grid: thin, the border colour, lines only along the value axis. */
export const GRID = { stroke: "var(--border)", strokeOpacity: 0.8 } as const;
/** The 2px gap between stacked segments is a stroke in the card's colour. */
export const GAP = { stroke: "var(--card)", strokeWidth: 2 } as const;

type SegmentProps = { x?: number; y?: number; width?: number; height?: number; fill?: string; corners: RoundedCorners; radius?: number };

/** One bar (or one segment of a stack), with rounded corners only where `corners` says. Recharts passes the geometry. */
export function Segment({ x = 0, y = 0, width = 0, height = 0, fill, corners, radius = 6 }: SegmentProps) {
  const d = RoundedRect.path(x, y, width, height, radius, corners);
  return d ? <path d={d} fill={fill} stroke="var(--card)" strokeWidth={2} /> : null;
}

/** What Recharts hands a custom bar shape that matters here: where the bar is, and the row it stands for. */
type BarGeometry = { x: number; y: number; width: number; height: number; payload?: unknown };

/** A bar segment from Recharts' shape props (their `radius` is not ours, so only the geometry is passed on). */
export function barSegment(props: BarGeometry, fill: string, corners: RoundedCorners, radius?: number) {
  const { x, y, width, height } = props;
  return <Segment x={x} y={y} width={width} height={height} fill={fill} corners={corners} radius={radius} />;
}

type TooltipRow = { label: string; value: string; color?: string };

/** The floating box of a chart: a title, then a row for each series, in the mono face. */
export function TooltipFrame({ title, rows }: { title: string; rows: readonly TooltipRow[] }) {
  return (
    <div className="grid min-w-40 gap-1 rounded-[10px] border bg-card px-2.5 py-2 text-[12.5px] shadow-card">
      <b className="font-extrabold">{title}</b>
      {rows.map((row) => (
        <div key={row.label} className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5 font-bold text-muted-foreground">
            {row.color ? <i aria-hidden="true" className="size-2 rounded-[2px]" style={{ background: row.color }} /> : null}
            {row.label}
          </span>
          <em className="font-mono not-italic tabular-nums">{row.value}</em>
        </div>
      ))}
    </div>
  );
}

/** The tooltip Recharts mounts for a chart: it hands over the hovered row, and `build` says what to show for it. */
export function ChartTip<T>({ active, payload, build }: { active?: boolean; payload?: readonly { payload?: T }[]; build: (row: T) => TooltipData }) {
  const row = payload?.[0]?.payload;
  return active && row ? <TooltipFrame {...build(row)} /> : null;
}

/** An axis label cut to fit its column, with an ellipsis. */
export function shorten(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
