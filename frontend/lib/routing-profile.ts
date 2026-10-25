import type { Effort, NodeRouting, ProfilePreview } from "@/lib/types";

export type ProfileChange = {
  key: string;
  /** The profile cannot be applied to this step as it is (the problems say why). */
  blocked: boolean;
  problems: string[];
  /** Model labels in priority order, before and after; null when the chain stays the same. */
  chain: { before: string[]; after: string[] } | null;
  effort: { before: Effort; after: Effort } | null;
  enabled: { before: boolean; after: boolean } | null;
};

export type MergeResult = { drafts: NodeRouting[]; applied: string[]; skipped: string[] };

/**
 * A profile preview, for review and for loading into the local routing edits. The preview endpoint saves nothing and
 * neither does this: applying only changes the edits, which are saved (or discarded) like any other edit.
 */
export class RoutingProfile {
  /** The steps the profile would change, in the order the preview lists them. */
  static changes(preview: ProfilePreview): ProfileChange[] {
    return preview.nodes
      .filter((entry) => entry.changed)
      .map(({ key, current, proposed, problems }) => {
        const unknownModel = proposed.bindings.filter((b) => b.model === null).map((b) => `${b.model_label} is not in the model list.`);
        // The API already says so for a model it lacks; this covers a preview that does not.
        const all = problems.length ? problems : unknownModel;
        const before = current.bindings.map((b) => b.model_label);
        const after = proposed.bindings.map((b) => b.model_label);
        return {
          key,
          blocked: all.length > 0,
          problems: all,
          chain: before.join("\n") === after.join("\n") ? null : { before, after },
          effort: current.reasoning_effort === proposed.reasoning_effort ? null : { before: current.reasoning_effort, after: proposed.reasoning_effort },
          enabled: current.enabled === proposed.enabled ? null : { before: current.enabled, after: proposed.enabled },
        };
      });
  }

  /**
   * The edits with the profile's steps loaded in. A step is loaded only when the profile changes it and can be applied;
   * every other step keeps whatever edits it has.
   */
  static merge(drafts: readonly NodeRouting[], preview: ProfilePreview): MergeResult {
    const changes = new Map(RoutingProfile.changes(preview).map((change) => [change.key, change]));
    const proposed = new Map(preview.nodes.map((entry) => [entry.key, entry.proposed]));
    const applied: string[] = [];
    const skipped: string[] = [];
    const merged = drafts.map((draft) => {
      const change = changes.get(draft.key);
      const next = proposed.get(draft.key);
      if (!change || !next) return draft;
      if (change.blocked) {
        skipped.push(draft.key);
        return draft;
      }
      applied.push(draft.key);
      return {
        ...draft,
        enabled: next.enabled,
        reasoning_effort: next.reasoning_effort,
        max_attempts: next.max_attempts,
        max_tool_steps: next.max_tool_steps,
        timeout_s: next.timeout_s,
        params_override: next.params_override,
        bindings: next.bindings,
      };
    });
    return { drafts: merged, applied, skipped };
  }

  static summary(changes: readonly ProfileChange[]): string {
    if (changes.length === 0) return "Nothing would change";
    const blocked = changes.filter((change) => change.blocked).length;
    const head = changes.length === 1 ? "1 step changes" : `${changes.length} steps change`;
    return blocked ? `${head} · ${blocked} cannot be applied` : head;
  }
}
