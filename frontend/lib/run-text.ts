import type { CallOutcome, CallStatus, ConsoleGraph, Money, RunStatus, Stage } from "@/lib/types";

export type StatusTone = "ok" | "bad" | "run" | "wait" | "off";

const JOBS: Record<ConsoleGraph, string> = {
  flow: "Lesson flow",
  study_material: "Study sheet",
  runtime_repair: "Repair",
  grade_test: "Grading",
};

const STATUSES: Record<RunStatus, { label: string; tone: StatusTone }> = {
  queued: { label: "Queued", tone: "off" },
  running: { label: "Running", tone: "run" },
  paused: { label: "Waiting for learner", tone: "wait" },
  succeeded: { label: "Finished", tone: "ok" },
  failed: { label: "Failed", tone: "bad" },
  cancelled: { label: "Stopped", tone: "off" },
};

const STAGES: Record<Stage, string> = {
  preparing_diagnostic: "Preparing quick check",
  awaiting_diagnostic: "Waiting for quick check",
  awaiting_prerequisite: "Waiting for foundations check",
  awaiting_choice: "Waiting for sheet choice",
  generating_material: "Writing study sheet",
  generating_lesson: "Building lesson",
  ready: "Ready",
  failed: "Failed",
};

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

/** The words and numbers of the console's run list and detail panel (staff read these, so internal terms are fine). */
export class RunText {
  /** "2.4 s", "41 s", "4 m 12 s", "1 h 05 m"; "—" when there is none. */
  static duration(seconds: number | null): string {
    if (seconds === null) return "—";
    if (seconds < 9.95) return `${Number(seconds.toFixed(1))} s`;
    const whole = Math.round(seconds);
    if (whole < MINUTE) return `${whole} s`;
    if (whole < HOUR) return `${Math.floor(whole / MINUTE)} m ${RunText.pad(whole % MINUTE)} s`;
    return `${Math.floor(whole / HOUR)} h ${RunText.pad(Math.floor((whole % HOUR) / MINUTE))} m`;
  }

  /** Dollars: three places under a cent, so a cheap run does not read as free; two otherwise. */
  static cost(money: Money | null): string {
    if (money === null) return "—";
    const dollars = Number(money);
    return `$${dollars.toFixed(dollars < 0.01 ? 3 : 2)}`;
  }

  static shortId(id: string): string {
    return id.slice(0, 8);
  }

  static job(graph: ConsoleGraph): string {
    return JOBS[graph] ?? graph;
  }

  static status(status: RunStatus): { label: string; tone: StatusTone } {
    return STATUSES[status];
  }

  /** Still moving by itself: a paused run is waiting for the learner, so nothing will happen to it. */
  static isActive(status: RunStatus): boolean {
    return status === "queued" || status === "running";
  }

  /** A model call's result: it worked, worked on a retry, or did not (an answer in the wrong shape is "invalid"). */
  static callResult(call: { outcome: CallOutcome; status: CallStatus }): { label: string; tone: StatusTone } {
    if (call.outcome === "ok") return { label: "ok", tone: "ok" };
    if (call.outcome === "retried") return { label: "retried", tone: "wait" };
    return { label: call.status === "invalid_output" ? "invalid" : "failed", tone: "bad" };
  }

  static stage(stage: Stage): string {
    return STAGES[stage] ?? String(stage).replaceAll("_", " ");
  }

  /** "just now", "12 min ago", "3 h ago", "2 d ago"; the date once it is over a month ago; "" for a bad time. */
  static ago(iso: string, now: Date = new Date(), locale?: string, timeZone?: string): string {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const seconds = (now.getTime() - then) / 1000;
    if (seconds < MINUTE) return "just now";
    if (seconds < HOUR) return `${Math.floor(seconds / MINUTE)} min ago`;
    if (seconds < DAY) return `${Math.floor(seconds / HOUR)} h ago`;
    if (seconds < 30 * DAY) return `${Math.floor(seconds / DAY)} d ago`;
    return new Date(then).toLocaleDateString(locale, { dateStyle: "medium", timeZone });
  }

  /** The exact time, for a hover title. */
  static exact(iso: string, locale?: string, timeZone?: string): string {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(locale, { dateStyle: "medium", timeStyle: "medium", timeZone, hour12: false });
  }

  private static pad(n: number): string {
    return String(n).padStart(2, "0");
  }
}
