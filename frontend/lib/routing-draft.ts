import type { ConsoleModel, ConsoleRouting, NodeRouting, NodeRoutingInput, RoutingBinding } from "@/lib/types";

/** What a step's chain gets when a model is added: the registry's own default for a fresh binding. */
const DEFAULT_RETRIES = 2;

/**
 * The local edits to the routing. Every operation returns a new step and leaves the old one alone, so the page can
 * keep the saved copy beside the edited one and tell, step by step, what Save has to send.
 */
export class RoutingDraft {
  /** The body of `PUT /console/nodes/{key}` for a step as it is now. The order of `bindings` is the priority. */
  static input(node: NodeRouting): NodeRoutingInput {
    return {
      enabled: node.enabled,
      reasoning_effort: node.reasoning_effort,
      max_attempts: node.max_attempts,
      max_tool_steps: node.max_tool_steps,
      timeout_s: node.timeout_s,
      params_override: node.params_override,
      bindings: node.bindings.map((b) => ({
        model: b.model as number,
        enabled: b.enabled,
        max_retries: b.max_retries,
        overrides: { params: b.overrides.params, reasoning_effort: b.overrides.reasoning_effort },
      })),
    };
  }

  /** The keys of the steps in `edited` that differ from `saved`, in the order of `saved` (the order of the page). */
  static changed(saved: readonly NodeRouting[], edited: readonly NodeRouting[]): string[] {
    const copies = new Map(edited.map((node) => [node.key, node]));
    return saved
      .filter((node) => {
        const copy = copies.get(node.key);
        return copy !== undefined && RoutingDraft.signature(copy) !== RoutingDraft.signature(node);
      })
      .map((node) => node.key);
  }

  static reorder(node: NodeRouting, from: number, to: number): NodeRouting {
    const last = node.bindings.length - 1;
    if (from === to || from < 0 || to < 0 || from > last || to > last) return node;
    const bindings = [...node.bindings];
    const [moved] = bindings.splice(from, 1);
    bindings.splice(to, 0, moved);
    return { ...node, bindings };
  }

  static moveUp(node: NodeRouting, index: number): NodeRouting {
    return RoutingDraft.reorder(node, index, index - 1);
  }

  /** A step always keeps one model: with none, every call would fail. */
  static canRemove(node: NodeRouting): boolean {
    return node.bindings.length > 1;
  }

  static remove(node: NodeRouting, index: number): NodeRouting {
    if (!RoutingDraft.canRemove(node) || index < 0 || index >= node.bindings.length) return node;
    return { ...node, bindings: node.bindings.filter((_, i) => i !== index) };
  }

  /** The model goes last: a fallback is what is tried when everything before it has failed. */
  static add(node: NodeRouting, model: ConsoleModel): NodeRouting {
    const binding: RoutingBinding = {
      model: model.id,
      model_label: `${model.provider}/${model.name}`,
      enabled: true,
      max_retries: DEFAULT_RETRIES,
      overrides: { params: {}, reasoning_effort: "" },
      problems: [],
    };
    return { ...node, bindings: [...node.bindings, binding] };
  }

  /** The models that can be added: on, with their provider's key set (the API refuses the rest), and not in the chain. */
  static fallbacks(node: NodeRouting, models: readonly ConsoleModel[]): ConsoleModel[] {
    const used = new Set(node.bindings.map((b) => b.model));
    return models.filter((m) => m.enabled && m.api_key_set && !used.has(m.id));
  }

  /** The steps of the API's routing in the order of the page (phases in lesson order). */
  static flatten(routing: ConsoleRouting): NodeRouting[] {
    return routing.phases.flatMap((phase) => phase.nodes);
  }

  /** The routing with `nodes` (the API's saved versions) in place of the steps of the same key. */
  static replace(routing: ConsoleRouting, nodes: readonly NodeRouting[]): ConsoleRouting {
    const saved = new Map(nodes.map((node) => [node.key, node]));
    return { phases: routing.phases.map((phase) => ({ ...phase, nodes: phase.nodes.map((node) => saved.get(node.key) ?? node) })) };
  }

  /** The changed steps in words, for the save bar. */
  static summary(keys: readonly string[]): string {
    return keys.join(", ");
  }

  /** Everything a save would send, as text: two steps with the same signature need no save. */
  private static signature(node: NodeRouting): string {
    return JSON.stringify(RoutingDraft.input(node));
  }
}
