import type { ConsoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { RoutingDraft } from "@/lib/routing-draft";
import type { NodeRouting } from "@/lib/types";

export type SaveOutcome = {
  /** The API's version of each step that was saved. */
  saved: NodeRouting[];
  /** The reasons, by step key, for each step that was not. */
  failed: Record<string, string[]>;
};

/** What the API calls a step's settings, for a refusal that is about one of them. */
const LABELS: Record<string, string> = {
  enabled: "Step enabled",
  reasoning_effort: "Reasoning effort",
  max_attempts: "Attempts",
  max_tool_steps: "Tool steps",
  timeout_s: "Timeout",
  params_override: "Parameters",
};

/**
 * Saves edited routing steps. The API replaces one step atomically, so several steps are several requests; each is kept
 * apart, so one refusal neither hides the saves that worked nor stops the rest.
 */
export class RoutingSaver {
  constructor(private readonly api: Pick<ConsoleApi, "saveNode">) {}

  async save(drafts: readonly NodeRouting[], keys: readonly string[]): Promise<SaveOutcome> {
    const outcome: SaveOutcome = { saved: [], failed: {} };
    for (const key of keys) {
      const draft = drafts.find((node) => node.key === key);
      if (!draft) {
        outcome.failed[key] = ["That step is not on this page any more. Reload and try again."];
        continue;
      }
      try {
        outcome.saved.push(await this.api.saveNode(key, RoutingDraft.input(draft)));
      } catch (error) {
        outcome.failed[key] = ConsoleFailure.of(error).lines(LABELS);
      }
    }
    return outcome;
  }

  /** The toast. */
  static message({ saved, failed }: SaveOutcome): string {
    const failures = Object.keys(failed).length;
    if (failures === 0) return "Routing saved. New lessons will use it.";
    const these = failures === 1 ? "1 could not be saved: see the notes on it." : `${failures} steps could not be saved: see the notes on them.`;
    if (saved.length === 0) return `Nothing was saved. ${these}`;
    return `Saved ${saved.length} ${saved.length === 1 ? "step" : "steps"}. ${these}`;
  }
}
