import { ConsoleFormat } from "@/lib/console-format";
import { ProviderSeries, type SeriesKey } from "@/lib/console-charts";
import type { ConsoleModel, NodePhase, NodeRouting } from "@/lib/types";

export type ChainChip = {
  /** The model without its provider ("gpt-oss-120b"). */
  name: string;
  /** provider/name, for the hover title. */
  full: string;
  series: SeriesKey;
  /** Switched off in the chain: kept, but not used. */
  parked: boolean;
};

const PHASES: Record<NodePhase, string> = {
  diagnose: "Diagnose",
  author: "Author",
  build: "Build",
  post: "After",
  onboarding: "Onboarding",
};

/** The words and marks of the Model routing page. */
export class RoutingView {
  static phase(phase: NodePhase): string {
    return PHASES[phase] ?? phase;
  }

  /** "high effort", "no reasoning" (a step that thinks nothing extra), or "off" (a step that does not run). */
  static effort(node: Pick<NodeRouting, "enabled" | "reasoning_effort">): string {
    if (!node.enabled) return "off";
    return node.reasoning_effort === "none" ? "no reasoning" : `${node.reasoning_effort} effort`;
  }

  static chain(node: Pick<NodeRouting, "bindings">): ChainChip[] {
    return node.bindings.map((binding) => {
      const [provider, ...rest] = binding.model_label.split("/");
      return {
        name: rest.length ? rest.join("/") : binding.model_label,
        full: binding.model_label,
        series: ProviderSeries.of(rest.length ? provider : ""),
        parked: !binding.enabled,
      };
    });
  }

  /** What a place in the chain means: the first is tried first, each later one only when the one before it has failed. */
  static caption(index: number): string {
    return index === 0 ? "Tried first" : `Used if #${index} fails`;
  }

  /** `undefined` is a model the registry does not list (a stale chain). */
  static price(model: Pick<ConsoleModel, "output_cost_per_mtok"> | undefined): string {
    if (!model) return "price unknown";
    if (model.output_cost_per_mtok === null) return "price not set";
    return Number(model.output_cost_per_mtok) === 0 ? "free" : `${ConsoleFormat.money(model.output_cost_per_mtok)}/M out`;
  }

  static requiredReason(node: Pick<NodeRouting, "optional">): string | null {
    return node.optional ? null : "Required step: lessons cannot build without it.";
  }

  /** The step the address names, if it is one of `keys`. */
  static selected(params: Pick<URLSearchParams, "get">, keys: readonly string[]): string | null {
    const key = params.get("node");
    return key && keys.includes(key) ? key : null;
  }

  static href(path: string, key: string | null): string {
    return key ? `${path}?node=${encodeURIComponent(key)}` : path;
  }
}
