import { PlainWarning } from "@/lib/plain-notes";
import type { NodeStatus, Route, RunEvent, Stage } from "@/lib/types";

type StepDef = {
  doing: string; // what the learner reads while it is pending or running
  done: string; // and once it is finished
  nodes: string[]; // graph nodes that belong to the step
  doneWhen: string; // the node whose completion finishes the step
  registry: string[]; // model-registry node keys (prefixes) whose retries/fallbacks are shown on the step
  /** The words for the foundations (prerequisite) check, where they differ. */
  foundations?: { doing: string; done: string };
  /** A sub-line while the step runs: how many times `node` has finished, said in words. */
  progress?: { node: string; text: (count: number) => string };
};

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

const STEPS: Record<string, StepDef> = {
  // The four parts of preparing a quick check (shown while it is being prepared) ...
  quiz_context: {
    doing: "Getting to know you",
    done: "Got to know you",
    nodes: ["load_context"],
    doneWhen: "load_context",
    registry: [],
  },
  quiz_write: {
    doing: "Writing your questions",
    done: "Wrote your questions",
    nodes: ["generate_diagnostic"],
    doneWhen: "generate_diagnostic",
    registry: ["diagnostic.generate"],
    foundations: { doing: "Writing your foundations questions", done: "Wrote your foundations questions" },
  },
  quiz_check: {
    doing: "Checking the questions",
    done: "Checked the questions",
    nodes: ["validate_diagnostic"],
    doneWhen: "validate_diagnostic",
    registry: ["diagnostic.review"],
  },
  quiz_publish: {
    doing: "Getting your quick check ready",
    done: "Your quick check is ready",
    nodes: ["publish_diagnostic"],
    doneWhen: "publish_diagnostic",
    registry: [],
    foundations: { doing: "Getting your foundations check ready", done: "Your foundations check is ready" },
  },
  // ... and all of it as one step, for the build that comes after (it is already done by then).
  quiz: {
    doing: "Preparing your quiz",
    done: "Prepared your quiz",
    nodes: ["load_context", "generate_diagnostic", "validate_diagnostic", "publish_diagnostic"],
    doneWhen: "publish_diagnostic",
    registry: ["diagnostic."],
  },
  assess: {
    doing: "Working out your starting point",
    done: "Worked out your starting point",
    nodes: ["grade_diagnostic", "publish_prerequisite", "grade_prerequisite", "assess_learner"],
    doneWhen: "assess_learner",
    registry: ["learner.assess"],
  },
  plan: {
    doing: "Planning the lesson",
    done: "Planned the lesson",
    nodes: ["plan_lesson", "validate_plan"],
    doneWhen: "validate_plan",
    registry: ["lesson.plan"],
  },
  write: {
    doing: "Writing pages",
    done: "Wrote the pages",
    nodes: ["write_page", "write_test", "authored_join"],
    doneWhen: "authored_join",
    registry: ["page.generate", "test.generate"],
    progress: { node: "write_page", text: (n) => `${Math.min(n, 3)} of 3 pages written` },
  },
  media: {
    doing: "Finding images & building interactives",
    done: "Found images & built interactives",
    nodes: ["plan_interactives", "validate_interactive_plan", "find_media", "build_interactive", "widgets_join"],
    doneWhen: "widgets_join",
    registry: ["interactive.", "media."],
    progress: { node: "build_interactive", text: (n) => `${plural(n, "interactive", "interactives")} built` },
  },
  check: {
    doing: "Checking it fits your level",
    done: "Checked it fits your level",
    nodes: ["alignment_judge", "fix_item"],
    doneWhen: "alignment_judge",
    registry: ["alignment."],
  },
  build: {
    doing: "Building the lesson",
    done: "Built the lesson",
    nodes: ["compile_page", "assemble_document", "repair_page", "repair_component"],
    doneWhen: "assemble_document",
    registry: ["page.compile", "code.repair"],
    progress: { node: "compile_page", text: (n) => `${Math.min(n, 3)} of 3 pages built` },
  },
  sandbox: {
    doing: "Test-driving it in a safe browser",
    done: "Test-drove it in a safe browser",
    nodes: ["render_check", "persist_lesson"],
    doneWhen: "persist_lesson",
    registry: [],
  },
  sheet_write: {
    doing: "Writing your study sheet",
    done: "Wrote your study sheet",
    nodes: ["generate_study_material"],
    doneWhen: "generate_study_material",
    registry: ["study."],
  },
  sheet_check: {
    doing: "Checking it",
    done: "Checked it",
    nodes: ["validate_study_material"],
    doneWhen: "validate_study_material",
    registry: [],
  },
  sheet_save: {
    doing: "Putting it together",
    done: "Put it together",
    nodes: ["persist_study_material"],
    doneWhen: "persist_study_material",
    registry: [],
  },
};

// A retry starts before the lesson says which stage it is back in: one calm step until it does (`setStage`).
STEPS.resume = { doing: "Picking up where it stopped", done: "Picked up where it stopped", nodes: [], doneWhen: "", registry: [] };

const ORDER_BY_STAGE: Partial<Record<Stage, string[]>> = {
  failed: ["resume"],
  preparing_diagnostic: ["quiz_context", "quiz_write", "quiz_check", "quiz_publish"],
  generating_material: ["sheet_write", "sheet_check", "sheet_save"],
  ready: ["sheet_write", "sheet_check", "sheet_save"], // the only run a ready lesson shows is another study sheet
  generating_lesson: ["quiz", "assess", "plan", "write", "media", "check", "build", "sandbox"],
};

/** Steps that finished in an earlier run of the lesson's flow, so no event of this run will say so. */
const DONE_BEFORE: Partial<Record<Stage, string[]>> = { generating_lesson: ["quiz"] };

export type StepStatus = "pending" | "running" | "done";
export type StepView = {
  key: string;
  label: string;
  status: StepStatus;
  /** How far the step has got, where the events allow ("2 of 3 pages written"); empty otherwise. */
  detail: string;
  /** How long the step took (or has taken so far), measured here; null when this client did not see it start. */
  elapsedMs: number | null;
};

type Timing = { start?: number; end?: number };

/**
 * The steps of the building screen, driven by run events. Pure state: feed it events, read `steps`, `percent`,
 * `headline`, `recovered` and `notes`. Which steps are shown depends on the stage the lesson is in (preparing the
 * quiz, writing a sheet, or building the lesson). Nothing technical is kept: no model names, no raw reasons.
 */
export class PipelineModel {
  private keys: string[] = [];
  private assumedDone = new Set<string>();
  private stage: Stage;
  private readonly nodeStatus = new Map<string, NodeStatus>();
  private readonly doneCount = new Map<string, number>();
  private readonly timings = new Map<string, Timing>();
  private readonly createdAt: number;
  warnings: string[] = [];
  /** When the run began (from the stream's snapshot), or null until it is known. */
  startedAt: number | null = null;
  /** A step needed a second try or a backup. The learner is told once, calmly, and never which model. */
  recovered = false;

  constructor(
    stage: Stage,
    private readonly clock: () => number = Date.now,
    /** The route, which tells a foundations check from a quick check while it is being prepared. */
    private readonly route: Route | "" = "",
  ) {
    this.stage = stage;
    this.configure(stage);
    this.createdAt = clock();
  }

  /** The lesson's stage became known (or changed) while the run goes on: show that stage's steps, keep every event seen. */
  setStage(stage: Stage): void {
    if (stage === this.stage) return;
    const before = this.statuses();
    this.stage = stage;
    this.configure(stage);
    this.time(before, false);
  }

  private configure(stage: Stage): void {
    this.keys = ORDER_BY_STAGE[stage] ?? ["quiz"];
    this.assumedDone = new Set(DONE_BEFORE[stage] ?? []);
  }

  apply(event: RunEvent): void {
    const before = this.statuses();
    const live = event.name !== "snapshot";
    switch (event.name) {
      case "snapshot":
        for (const [node, status] of Object.entries(event.data.node_status)) this.nodeStatus.set(node, status);
        if (event.data.started_at) {
          const started = Date.parse(event.data.started_at);
          this.startedAt = Number.isNaN(started) ? null : started;
        }
        break;
      case "node":
        this.nodeStatus.set(event.data.node, event.data.status);
        if (event.data.status === "done") this.doneCount.set(event.data.node, (this.doneCount.get(event.data.node) ?? 0) + 1);
        if (event.data.status === "retrying" && this.stepOfNode(event.data.node)) this.recovered = true;
        break;
      case "model":
        if (this.stepOfRegistry(event.data.node)) this.recovered = true;
        break;
      case "warning":
        this.warnings.push(event.data.message);
        break;
    }
    this.time(before, live);
  }

  get steps(): StepView[] {
    return this.stepsAt(this.clock());
  }

  /** The steps as they stand at `now` (a running step's time keeps counting). */
  stepsAt(now: number): StepView[] {
    return this.keys.map((key) => {
      const status = this.statusOf(key);
      const def = STEPS[key];
      const count = def.progress ? (this.doneCount.get(def.progress.node) ?? 0) : 0;
      return {
        key,
        label: this.wording(def)[status === "done" ? "done" : "doing"],
        status,
        detail: status === "running" && def.progress && count > 0 ? def.progress.text(count) : "",
        elapsedMs: this.elapsed(key, status, now),
      };
    });
  }

  /** Steps done out of all of them, as a whole percent. */
  get percent(): number {
    return Math.round((100 * this.doneSteps) / this.keys.length);
  }

  /** There is something to show a percentage of: at least one step of this run is done. Before that the bar just
   *  moves, even when a step finished in an earlier run (the quiz), so a build never opens at "13%". */
  get measurable(): boolean {
    return this.keys.some((key) => !this.assumedDone.has(key) && this.statusOf(key) === "done");
  }

  private get doneSteps(): number {
    return this.keys.filter((key) => this.statusOf(key) === "done").length;
  }

  private wording(def: StepDef): { doing: string; done: string } {
    return this.route === "prerequisite" && def.foundations ? def.foundations : def;
  }

  /** What is being worked on, in friendly words. */
  get headline(): string {
    const current = this.keys.find((key) => this.statusOf(key) === "running") ?? this.keys.find((key) => this.statusOf(key) === "pending");
    return current ? this.wording(STEPS[current]).doing : "All done";
  }

  /** The builder's small notes, in plain words and without repeats. */
  get notes(): string[] {
    return PlainWarning.all(this.warnings);
  }

  private statuses(): Map<string, StepStatus> {
    return new Map(this.keys.map((key) => [key, this.statusOf(key)]));
  }

  private statusOf(key: string): StepStatus {
    const def = STEPS[key];
    if (this.assumedDone.has(key)) return "done";
    if (def.nodes.some((node) => ["running", "retrying"].includes(this.nodeStatus.get(node) ?? ""))) return "running";
    if (this.nodeStatus.get(def.doneWhen) === "done") return "done";
    return def.nodes.some((node) => this.nodeStatus.get(node) === "done") ? "running" : "pending";
  }

  /** Notes when each step started and ended. A step first seen running starts now; one first seen done started when
   *  the step before it ended (or when the build began). A snapshot only says where things stand, not when. */
  private time(before: Map<string, StepStatus>, live: boolean): void {
    const now = this.clock();
    let previousEnd = this.createdAt;
    for (const key of this.keys) {
      const was = before.get(key);
      const status = this.statusOf(key);
      const timing = this.timings.get(key) ?? {};
      if (status !== "pending" && was === "pending" && !this.assumedDone.has(key)) {
        if (status === "running") timing.start = now;
        else if (live) timing.start = previousEnd;
      }
      if (status === "done" && was !== "done" && !this.assumedDone.has(key)) {
        timing.end = now;
        if (timing.start === undefined && live && was === "running") timing.start = previousEnd;
      }
      this.timings.set(key, timing);
      previousEnd = timing.end ?? previousEnd;
    }
  }

  private elapsed(key: string, status: StepStatus, now: number): number | null {
    const timing = this.timings.get(key);
    if (!timing || timing.start === undefined || status === "pending") return null;
    return (status === "done" ? (timing.end ?? now) : now) - timing.start;
  }

  private stepOfNode(node: string): string | undefined {
    return this.keys.find((key) => STEPS[key].nodes.includes(node));
  }

  private stepOfRegistry(registryKey: string): string | undefined {
    return this.keys.find((key) => STEPS[key].registry.some((prefix) => registryKey.startsWith(prefix)));
  }
}

/** A step's time in the words of a clock: "12s", "2m 05s". */
export class Elapsed {
  static format(ms: number): string {
    const seconds = Math.floor(ms / 1000);
    return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
  }
}
