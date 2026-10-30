import { RoundedRect } from "@/lib/chart-shapes";
import type { AttemptHistory, AttemptStatus, AttemptSummary, ScoreBand, TrendPoint } from "@/lib/types";

export type HistoryRow = {
  attemptNo: number;
  title: string;
  /** "16 of 20", or empty until the attempt is graded. */
  marks: string;
  percentText: string;
  percent: number | null;
  band: string;
  /** What is going on, for an attempt that is not graded; empty for a graded one. */
  state: string;
  duration: string;
  /** How it compares with the last attempt and with the best before it. */
  changes: string[];
  best: boolean;
  submittedAt: string | null;
};

const BANDS: Record<ScoreBand, string> = { "": "", fail: "Needs another go", normal: "Good", excellent: "Excellent" };
const STATES: Record<Exclude<AttemptStatus, "graded">, string> = {
  generating: "Getting questions ready",
  in_progress: "In progress",
  grading: "Being marked",
  failed: "Needs marking again",
};

/** How a lesson's attempts are told to the learner: newest first, each compared with the one before and with the best. */
export class AttemptHistoryView {
  static rows(history: AttemptHistory): HistoryRow[] {
    const points = new Map(history.trend.series.map((p) => [p.attempt_no, p]));
    return [...history.attempts]
      .sort((a, b) => b.attempt_no - a.attempt_no)
      .map((attempt) => AttemptHistoryView.row(attempt, points.get(attempt.attempt_no), history.trend.best_attempt_no));
  }

  /** "2 min 5 s", "1 h 1 min", "45 s"; empty when the time is not known. */
  static duration(seconds: number | null): string {
    if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return "";
    const whole = Math.round(seconds);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const rest = whole % 60;
    if (hours) return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
    if (minutes) return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
    return `${rest} s`;
  }

  private static row(attempt: AttemptSummary, point: TrendPoint | undefined, bestNo: number | null): HistoryRow {
    const graded = attempt.status === "graded" && attempt.percent !== null;
    return {
      attemptNo: attempt.attempt_no,
      title: `Attempt ${attempt.attempt_no}`,
      marks: graded ? `${attempt.awarded} of ${attempt.available}` : "",
      percentText: graded ? `${attempt.percent}%` : "",
      percent: graded ? attempt.percent : null,
      band: graded ? BANDS[attempt.band] : "",
      state: attempt.status === "graded" ? "" : STATES[attempt.status],
      duration: AttemptHistoryView.duration(attempt.duration_s),
      changes: point ? AttemptHistoryView.changes(point) : [],
      best: graded && attempt.attempt_no === bestNo,
      submittedAt: attempt.submitted_at,
    };
  }

  private static changes(point: TrendPoint): string[] {
    const lines: string[] = [];
    if (point.delta_previous !== null) {
      const n = Math.abs(point.delta_previous);
      lines.push(point.delta_previous === 0 ? "Same as last time" : `${point.delta_previous > 0 ? "Up" : "Down"} ${n} ${n === 1 ? "point" : "points"} on last time`);
    }
    if (point.delta_best !== null) {
      const n = Math.abs(point.delta_best);
      lines.push(point.delta_best > 0 ? "A new best" : point.delta_best === 0 ? "Level with your best" : `${n} ${n === 1 ? "point" : "points"} under your best`);
    }
    return lines;
  }
}

export type ChartBar = { attemptNo: number; x: number; y: number; width: number; height: number; path: string; label: string; best: boolean };

/** The small bar chart of the graded attempts: one bar each, as tall as its percent, drawn with the shared bar outline. */
export class AttemptChart {
  static readonly GAP = 6;
  static readonly MAX_BAR = 36;

  /** `floor` is what every bar shows even at 0% (so a failed attempt is still a mark on the chart); a full score fills
   *  the height. `bestNo` marks one bar. */
  static bars(series: TrendPoint[], width: number, height: number, floor = 2, bestNo: number | null = null): ChartBar[] {
    if (series.length === 0 || !(width > 0) || !(height > 0)) return [];
    const slot = (width - AttemptChart.GAP * (series.length - 1)) / series.length;
    const barWidth = Math.max(1, Math.min(slot, AttemptChart.MAX_BAR));
    const total = barWidth * series.length + AttemptChart.GAP * (series.length - 1);
    const left = (width - total) / 2;
    return series.map((p, index) => {
      const barHeight = floor + Math.round((Math.min(Math.max(p.percent, 0), 100) / 100) * (height - floor));
      const x = left + index * (barWidth + AttemptChart.GAP);
      const y = height - barHeight;
      return {
        attemptNo: p.attempt_no,
        x, y, width: barWidth, height: barHeight,
        path: RoundedRect.path(x, y, barWidth, barHeight, 4, "top"),
        label: `Attempt ${p.attempt_no}: ${p.percent}%`,
        best: p.attempt_no === bestNo,
      };
    });
  }
}
