import { RunText } from "@/lib/run-text";
import type { TimelineState, TimelineStep } from "@/lib/types";

type Phase = TimelineStep["phase"];

export type Bar = { left: number; width: number };
export type Lane = {
  /** Unique within the run, since the same node can appear more than once. */
  key: string;
  node: string;
  state: TimelineState;
  /** Percentages of the lane; null when the step's time was not kept. */
  bar: Bar | null;
  durationText: string;
  tip: { title: string; rows: [string, string][] };
  tipAlign: "start" | "center" | "end";
  /** The lane as one sentence, for assistive technology. */
  label: string;
};
export type PhaseGroup = { phase: Phase; label: string; lanes: Lane[] };
export type TimelineView = { phases: PhaseGroup[]; totalS: number };

const PHASES: { phase: Phase; label: string }[] = [
  { phase: "diagnose", label: "Diagnose" },
  { phase: "author", label: "Author" },
  { phase: "build", label: "Build" },
  { phase: "post", label: "After" },
  { phase: "other", label: "Other" },
];

const RESULTS: Record<TimelineState, string> = {
  ran: "Ran",
  retried: "Ran again after a failed check",
  failed: "Failed",
  waiting: "Waiting for the learner",
};

/** Lays a run's steps out for the timeline: phases in order, one lane per step, bars as percentages of the run. */
export class RunTimeline {
  /** A step this short would vanish, so its bar is at least this wide (percent of the lane). */
  static readonly MIN_WIDTH = 1.5;

  /** `runDurationS` is the run's own time so far, which outlasts the last step while it waits for the learner. */
  static layout(steps: TimelineStep[], runDurationS: number | null): TimelineView {
    const totalS = RunTimeline.total(steps, runDurationS);
    const groups = new Map<Phase, Lane[]>();
    steps.forEach((step, index) => {
      const phase = PHASES.some((p) => p.phase === step.phase) ? step.phase : "other";
      groups.set(phase, [...(groups.get(phase) ?? []), RunTimeline.lane(step, index, totalS)]);
    });
    const phases = PHASES.filter((p) => groups.has(p.phase)).map((p) => ({ ...p, lanes: groups.get(p.phase)! }));
    return { phases, totalS };
  }

  private static total(steps: TimelineStep[], runDurationS: number | null): number {
    const ends = steps.map((s) => (s.start_offset_s ?? 0) + (s.duration_s ?? 0));
    return Math.max(1, runDurationS ?? 0, ...ends);
  }

  private static lane(step: TimelineStep, index: number, totalS: number): Lane {
    const bar = RunTimeline.bar(step, totalS);
    const started = step.start_offset_s === null ? "—" : `${RunText.duration(step.start_offset_s)} into the run`;
    const took = RunText.duration(step.state === "waiting" ? null : step.duration_s);
    const result = RESULTS[step.state];
    return {
      key: `${index}:${step.node}`,
      node: step.node,
      state: step.state,
      bar,
      durationText: took,
      tip: { title: step.node, rows: [["Result", result], ["Started", started], ["Took", took]] },
      tipAlign: RunTimeline.align(bar),
      label: RunTimeline.sentence(step, result, took),
    };
  }

  private static bar(step: TimelineStep, totalS: number): Bar | null {
    if (step.start_offset_s === null) return null;
    // A step that is waiting has no end: it lasts as long as the run has.
    const length = step.state === "waiting" ? totalS - step.start_offset_s : (step.duration_s ?? 0);
    const width = Math.min(100, Math.max(RunTimeline.MIN_WIDTH, (length / totalS) * 100));
    const left = Math.min((step.start_offset_s / totalS) * 100, 100 - width);
    return { left, width };
  }

  private static align(bar: Bar | null): Lane["tipAlign"] {
    if (!bar) return "center";
    const middle = bar.left + bar.width / 2;
    return middle < 20 ? "start" : middle > 80 ? "end" : "center";
  }

  private static sentence(step: TimelineStep, result: string, took: string): string {
    const parts = [`${step.node}: ${result}.`];
    if (step.start_offset_s !== null) parts.push(`Started ${RunText.duration(step.start_offset_s)} into the run.`);
    if (took !== "—") parts.push(`Took ${took}.`);
    return parts.join(" ");
  }
}
