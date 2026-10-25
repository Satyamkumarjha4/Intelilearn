import { ProviderSeries } from "@/lib/console-charts";
import type { ConsoleModel, ConsoleProvider, UsageFilters } from "@/lib/types";

export type FilterOption = { value: string; label?: string };

/** The choices in the usage page's drop-downs, and the rule that a model must belong to the chosen provider. */
export class UsageFilterOptions {
  /** By key (what the API filters on), named like the charts name them; a provider the charts do not know keeps its key. */
  static providers(providers: readonly Pick<ConsoleProvider, "key">[]): FilterOption[] {
    return providers.map(({ key }) => {
      const series = ProviderSeries.of(key);
      return { value: key, label: series === "other" ? key : ProviderSeries.label(series) };
    });
  }

  /** Each model name once, sorted; only the chosen provider's when one is chosen. */
  static models(models: readonly Pick<ConsoleModel, "name" | "provider">[], provider: string): FilterOption[] {
    const names = new Set(models.filter((model) => !provider || model.provider === provider).map((model) => model.name));
    return [...names].sort((a, b) => a.localeCompare(b)).map((value) => ({ value }));
  }

  /** In the order given: the lesson's order. */
  static steps(keys: readonly string[]): FilterOption[] {
    return keys.map((value) => ({ value }));
  }

  static outcomes(): FilterOption[] {
    return [
      { value: "ok", label: "Worked" },
      { value: "retried", label: "Worked after retry" },
      { value: "failed", label: "Failed" },
    ];
  }

  /** The filters with a change applied; a model that the new provider does not serve is cleared, so the page is not
   *  left empty for a reason nobody can see. */
  static change(
    filters: UsageFilters,
    patch: Partial<UsageFilters>,
    models: readonly Pick<ConsoleModel, "name" | "provider">[],
  ): UsageFilters {
    const next = { ...filters, ...patch };
    if (patch.provider && next.model && !models.some((m) => m.provider === patch.provider && m.name === next.model)) next.model = "";
    return next;
  }
}
