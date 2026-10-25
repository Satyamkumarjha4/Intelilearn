import { LevelMeter } from "@/components/lessons/level-meter";

type Props = { filled: number; label: string; animate?: boolean };

/** The level meter with its two ends and where the learner sits between them. */
export function LevelReadout({ filled, label, animate }: Props) {
  return (
    <div className="flex flex-col gap-1.5">
      <LevelMeter filled={filled} total={5} label={label} animate={animate} />
      <div className="flex justify-between text-xs font-bold text-muted-foreground" aria-hidden="true">
        <span>New to it</span>
        <b className="text-insight-text">{label}</b>
        <span>Expert</span>
      </div>
    </div>
  );
}
