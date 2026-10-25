import { Sparkline as SparklineShape } from "@/lib/console-charts";

/** A small line through a series, for a tile. The line is the whole story; the numbers are in the tile and its table. */
export function Sparkline({ values, label }: { values: readonly (number | null)[]; label: string }) {
  const { path } = SparklineShape.shape(values);
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${SparklineShape.WIDTH} ${SparklineShape.HEIGHT}`} preserveAspectRatio="none" className="block h-[34px] w-full">
      <title>{label}</title>
      {path ? <path d={path} fill="none" stroke="var(--primary)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" /> : null}
    </svg>
  );
}
