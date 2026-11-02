import { PlainWarning } from "@/lib/plain-notes";
import { StarScale } from "@/lib/star-scale";
import type { LessonDetail, NodeStatus, Route, RunEvent, Stage } from "@/lib/types";

type StepDef = {
  doing: string; // what the learner reads while it is pending or running
  done: string; // and once it is finished
  nodes: string[]; // graph nodes that belong to the step
  doneWhen: string; // the node whose completion finishes the step
  registry: string[]; // model-registry node keys (prefixes) whose retries/fallbacks are shown on the step
  /** The words for the basics (prerequisite) check, where they differ. */
  foundations?: { doing: string; done: string };
  /** A sub-line while the step runs: how many times `node` has finished, said in words. */
  progress?: { node: string; text: (count: number) => string };
  /** For a step several branches of one node make: it is done once `node` has finished `count` times. */
  doneAfter?: { node: string; count: number };
  /** For a step whose branches are joined by a node: it is done once that node has started (the number of branches
   *  does not matter, and it is not known to the page). */
  doneOnceStarted?: string;
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
    foundations: { doing: "Writing your basics questions", done: "Wrote your basics questions" },
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
    foundations: { doing: "Getting your basics check ready", done: "Your basics check is ready" },
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
  // A lesson the learner rated themselves into has no quick check: it starts from the rating ...
  rated_start: {
    doing: "Setting your starting point",
    done: "Set your starting point",
    nodes: ["load_context", "entry_router", "assess_from_source", "level_gate"],
    doneWhen: "assess_from_source",
    registry: [],
  },
  // ... and a Beginner, who was not tested, gets the things to learn first chosen for them.
  prerequisites: {
    doing: "Choosing what to learn first",
    done: "Chose what to learn first",
    nodes: ["plan_prerequisites", "validate_prerequisites"],
    doneWhen: "validate_prerequisites",
    registry: ["prerequisites."],
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
  // Sheets written together (the choice after a perfect quick check, a lesson that asked for sheets, more sheets for a
  // lesson that is ready) have their own steps, for one sheet or two.
  sheets_write: {
    doing: "Writing your study sheets",
    done: "Wrote your study sheets",
    nodes: ["plan_sheets", "generate_sheet"],
    doneWhen: "",
    doneOnceStarted: "sheets_join",
    registry: ["study."],
    progress: { node: "generate_sheet", text: (n) => `${plural(n, "sheet", "sheets")} written` },
  },
  sheets_save: {
    doing: "Checking and putting them together",
    done: "Checked and put them together",
    nodes: ["sheets_join"],
    doneWhen: "sheets_join",
    registry: [],
  },
};

const SHEET_PAIR_STEPS = ["sheets_write", "sheets_save"];

// A retry starts before the lesson says which stage it is back in: one calm step until it does (`setStage`).
STEPS.resume = { doing: "Picking up where it stopped", done: "Picked up where it stopped", nodes: [], doneWhen: "", registry: [] };

const ORDER_BY_STAGE: Partial<Record<Stage, string[]>> = {
  failed: ["resume"],
  preparing_diagnostic: ["quiz_context", "quiz_write", "quiz_check", "quiz_publish"],
  generating_material: SHEET_PAIR_STEPS,
  ready: SHEET_PAIR_STEPS, // the only run a ready lesson shows is more study sheets
  generating_lesson: ["quiz", "assess", "plan", "write", "media", "check", "build", "sandbox"],
};

/**
 * How a lesson's steps differ by how its level was found (a quick check, the default, or the learner's own rating) and
 * by what it was asked for (`sheets`: study sheets only, so it has no pages to plan and no prerequisites to choose).
 */
export type PipelinePath = { rated: boolean; beginner: boolean; sheets?: boolean };

export class PipelinePaths {
  static readonly QUICK_CHECK: PipelinePath = { rated: false, beginner: false };

  /** From the lesson: a rating and, for the stars of a Beginner, the step that chooses their prerequisites. */
  static of(lesson: Pick<LessonDetail, "entry" | "self_rating" | "intent">): PipelinePath {
    const rated = lesson.entry === "self_rating";
    const sheets = lesson.intent === "sheets";
    return { rated, beginner: !sheets && rated && StarScale.levelOf(StarScale.halvesOf(lesson.self_rating)) === "beginner", sheets };
  }

  /** The steps of a stage on this path. A lesson with no quick check has none to prepare or to have finished before. */
  static order(stage: Stage, path: PipelinePath): string[] {
    if (path.sheets && stage === "generating_material") return [path.rated ? "rated_start" : "assess", ...SHEET_PAIR_STEPS];
    if (path.rated && stage === "preparing_diagnostic") return ["rated_start"];
    if (path.rated && stage === "generating_lesson") {
      return ["rated_start", ...(path.beginner ? ["prerequisites"] : []), "plan", "write", "media", "check", "build", "sandbox"];
    }
    return ORDER_BY_STAGE[stage] ?? ["quiz"];
  }

  static doneBefore(stage: Stage, path: PipelinePath): string[] {
    return path.rated ? [] : (DONE_BEFORE[stage] ?? []);
  }
}

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
    /** The route, which tells a basics check from a quick check while it is being prepared. */
    private readonly route: Route | "" = "",
    /** How the level was found, which decides whether there is a quick check to prepare and prerequisites to choose. */
    private readonly path: PipelinePath = PipelinePaths.QUICK_CHECK,
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
    this.keys = PipelinePaths.order(stage, this.path);
    this.assumedDone = new Set(PipelinePaths.doneBefore(stage, this.path));
  }

  apply(event: RunEvent): void {
    const before = this.statuses();
    const live = event.name !== "snapshot";
    switch (event.name) {
      case "snapshot":
        for (const [node, status] of Object.entries(event.data.node_status)) {
          this.nodeStatus.set(node, status);
        }
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
    if (def.doneAfter && (this.doneCount.get(def.doneAfter.node) ?? 0) >= def.doneAfter.count) return "done";
    if (def.doneOnceStarted && this.nodeStatus.has(def.doneOnceStarted)) return "done";
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
