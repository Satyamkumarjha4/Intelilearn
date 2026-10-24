import type { NodeStatus, RunEvent, Stage } from "@/lib/types";

type StepDef = {
  label: string;
  nodes: string[]; // graph nodes that belong to the step
  doneWhen: string; // the node whose completion finishes the step
  registry: string[]; // model-registry node keys (prefixes) whose retries/fallbacks are shown on the step
};

const STEPS: Record<string, StepDef> = {
  quiz: {
    label: "Preparing your quiz",
    nodes: ["load_context", "generate_diagnostic", "validate_diagnostic", "publish_diagnostic"],
    doneWhen: "publish_diagnostic",
    registry: ["diagnostic."],
  },
  assess: {
    label: "Assessing your level",
    nodes: ["grade_diagnostic", "publish_prerequisite", "grade_prerequisite", "assess_learner"],
    doneWhen: "assess_learner",
    registry: ["learner.assess"],
  },
  plan: {
    label: "Planning the lesson",
    nodes: ["plan_lesson", "validate_plan"],
    doneWhen: "validate_plan",
    registry: ["lesson.plan"],
  },
  write: {
    label: "Writing pages",
    nodes: ["write_page", "write_test", "authored_join"],
    doneWhen: "authored_join",
    registry: ["page.generate", "test.generate"],
  },
  media: {
    label: "Finding media & building interactives",
    nodes: ["plan_interactives", "validate_interactive_plan", "find_media", "build_interactive", "widgets_join"],
    doneWhen: "widgets_join",
    registry: ["interactive.", "media."],
  },
  check: {
    label: "Checking content",
    nodes: ["alignment_judge", "fix_item"],
    doneWhen: "alignment_judge",
    registry: ["alignment."],
  },
  build: {
    label: "Building the lesson",
    nodes: ["compile_page", "assemble_document", "repair_page", "repair_component"],
    doneWhen: "assemble_document",
    registry: ["page.compile", "code.repair"],
  },
  sandbox: {
    label: "Testing in the sandbox",
    nodes: ["render_check", "persist_lesson"],
    doneWhen: "persist_lesson",
    registry: [],
  },
  sheet: {
    label: "Writing your study sheet",
    nodes: ["generate_study_material", "validate_study_material", "persist_study_material"],
    doneWhen: "persist_study_material",
    registry: ["study."],
  },
};

const ORDER_BY_STAGE: Partial<Record<Stage, string[]>> = {
  preparing_diagnostic: ["quiz"],
  generating_material: ["sheet"],
  generating_lesson: ["assess", "plan", "write", "media", "check", "build", "sandbox"],
};

export type StepStatus = "pending" | "running" | "done";
export type StepView = { label: string; status: StepStatus; note: string };

/**
 * The steps of the progress screen, driven by run events. Pure state: feed it events, read `steps`.
 * Which steps are shown depends on the stage the lesson is in (preparing the quiz, writing a sheet, or the lesson).
 */
export class PipelineModel {
  private readonly keys: string[];
  private readonly nodeStatus = new Map<string, NodeStatus>();
  private readonly notes = new Map<string, string>();
  warnings: string[] = [];

  constructor(stage: Stage) {
    this.keys = ORDER_BY_STAGE[stage] ?? ["quiz"];
  }

  apply(event: RunEvent): void {
    switch (event.name) {
      case "snapshot":
        for (const [node, status] of Object.entries(event.data.node_status)) this.nodeStatus.set(node, status);
        break;
      case "node": {
        this.nodeStatus.set(event.data.node, event.data.status);
        const key = this.stepOfNode(event.data.node);
        if (key && event.data.status === "retrying") {
          this.notes.set(key, `Trying again (attempt ${event.data.attempt ?? "?"}): ${event.data.reason ?? ""}`.trim());
        } else if (key && event.data.status !== "pending") {
          this.notes.delete(key);
        }
        break;
      }
      case "model": {
        const key = this.stepOfRegistry(event.data.node);
        if (key) {
          this.notes.set(
            key,
            event.data.kind === "fallback"
              ? `Switched to ${event.data.model} (${event.data.reason})`
              : `Retrying ${event.data.model} (${event.data.reason})`,
          );
        }
        break;
      }
      case "warning":
        this.warnings.push(event.data.message);
        break;
    }
  }

  get steps(): StepView[] {
    return this.keys.map((key) => ({
      label: STEPS[key].label,
      status: this.statusOf(key),
      note: this.notes.get(key) ?? "",
    }));
  }

  private statusOf(key: string): StepStatus {
    const def = STEPS[key];
    if (def.nodes.some((node) => ["running", "retrying"].includes(this.nodeStatus.get(node) ?? ""))) return "running";
    if (this.nodeStatus.get(def.doneWhen) === "done") return "done";
    return def.nodes.some((node) => this.nodeStatus.get(node) === "done") ? "running" : "pending";
  }

  private stepOfNode(node: string): string | undefined {
    return this.keys.find((key) => STEPS[key].nodes.includes(node));
  }

  private stepOfRegistry(registryKey: string): string | undefined {
    return this.keys.find((key) => STEPS[key].registry.some((prefix) => registryKey.startsWith(prefix)));
  }
}
