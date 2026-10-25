import { ApiError } from "@/lib/api";
import type { ConsoleModel, ConsoleProvider, ModelChanges, NewModel, ProviderChanges } from "@/lib/types";

type Method = ConsoleModel["structured_output_method"];
type Control = ConsoleModel["reasoning_control"];

/** What the boxes of the model form hold: text for numbers and for the default parameters. */
export type ModelFormValues = {
  provider: string;
  name: string;
  label: string;
  enabled: boolean;
  context_window: string;
  max_output_tokens: string;
  rpm_limit: string;
  input_cost_per_mtok: string;
  output_cost_per_mtok: string;
  supports_structured_output: boolean;
  structured_output_method: Method;
  supports_tool_calling: boolean;
  supports_parallel_tool_calls: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
  reasoning_control: Control;
  reasoning_disables_sampling: boolean;
  default_params: string;
};
export type FormErrors<T> = Partial<Record<keyof T, string>>;

const WHOLE = "Enter a whole number, 1 or more.";
const LIMIT = "Leave blank for no limit, or enter a whole number, 1 or more.";
const PRICE = "Enter dollars per million tokens, like 0.15, or leave blank.";
const PARAMS = 'Enter a JSON object like {"temperature": 0.4}.';
const NAME_MAX = 150;
const BOOLEANS = [
  "enabled",
  "supports_structured_output",
  "supports_tool_calling",
  "supports_parallel_tool_calls",
  "supports_vision",
  "supports_reasoning",
  "reasoning_disables_sampling",
] as const;
const CHOICES = ["structured_output_method", "reasoning_control"] as const;

function firstMessages(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  return Object.fromEntries(Object.entries(error.fields).filter(([, messages]) => messages.length).map(([field, messages]) => [field, messages[0]]));
}

/** A whole number of at least 1 from text, or null. */
function positive(text: string): number | null {
  const trimmed = text.trim();
  return /^\d+$/.test(trimmed) && Number(trimmed) >= 1 ? Number(trimmed) : null;
}

/** `{...}` from the default-parameters box (an empty box is `{}`), or null if it is not a JSON object. */
function params(text: string): Record<string, unknown> | null {
  if (!text.trim()) return {};
  try {
    const value: unknown = JSON.parse(text);
    return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** Keys in a fixed order, so two objects with the same content compare equal. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** The model form: its starting values, what is wrong with them, and the request that saving sends. */
export class ModelForm {
  static blank(provider: string): ModelFormValues {
    return {
      provider,
      name: "",
      label: "",
      enabled: true,
      context_window: "128000",
      max_output_tokens: "8192",
      rpm_limit: "",
      input_cost_per_mtok: "",
      output_cost_per_mtok: "",
      supports_structured_output: false,
      structured_output_method: "json_schema",
      supports_tool_calling: false,
      supports_parallel_tool_calls: false,
      supports_vision: false,
      supports_reasoning: false,
      reasoning_control: "none",
      reasoning_disables_sampling: false,
      default_params: "{}",
    };
  }

  static fromModel(model: ConsoleModel): ModelFormValues {
    return {
      ...ModelForm.blank(model.provider),
      name: model.name,
      label: model.label,
      enabled: model.enabled,
      context_window: String(model.context_window),
      max_output_tokens: String(model.max_output_tokens),
      rpm_limit: model.rpm_limit === null ? "" : String(model.rpm_limit),
      input_cost_per_mtok: ModelForm.priceText(model.input_cost_per_mtok),
      output_cost_per_mtok: ModelForm.priceText(model.output_cost_per_mtok),
      supports_structured_output: model.supports_structured_output,
      structured_output_method: model.structured_output_method,
      supports_tool_calling: model.supports_tool_calling,
      supports_parallel_tool_calls: model.supports_parallel_tool_calls,
      supports_vision: model.supports_vision,
      supports_reasoning: model.supports_reasoning,
      reasoning_control: model.reasoning_control,
      reasoning_disables_sampling: model.reasoning_disables_sampling,
      default_params: Object.keys(model.default_params).length ? JSON.stringify(model.default_params, null, 2) : "{}",
    };
  }

  static errors(values: ModelFormValues, mode: "add" | "edit"): FormErrors<ModelFormValues> {
    const errors: FormErrors<ModelFormValues> = {};
    if (mode === "add" && !values.provider) errors.provider = "Choose a provider.";
    if (!values.name.trim()) errors.name = "Enter the model id the provider uses.";
    else if (values.name.trim().length > NAME_MAX) errors.name = `At most ${NAME_MAX} characters.`;
    if (positive(values.context_window) === null) errors.context_window = WHOLE;
    if (positive(values.max_output_tokens) === null) errors.max_output_tokens = WHOLE;
    if (values.rpm_limit.trim() && positive(values.rpm_limit) === null) errors.rpm_limit = LIMIT;
    for (const field of ["input_cost_per_mtok", "output_cost_per_mtok"] as const) {
      const message = ModelForm.priceError(values[field]);
      if (message) errors[field] = message;
    }
    if (params(values.default_params) === null) errors.default_params = PARAMS;
    if (values.supports_reasoning && values.reasoning_control === "none") {
      errors.reasoning_control = "Choose how reasoning is controlled for a reasoning model.";
    }
    return errors;
  }

  /** The body of `POST /console/models`. Assumes the values passed `errors`. */
  static newModel(values: ModelFormValues): NewModel {
    return {
      provider: values.provider,
      name: values.name.trim(),
      label: values.label.trim(),
      ...ModelForm.settings(values),
    };
  }

  /** The body of `PATCH /console/models/{id}`: only what differs from `model`. Assumes the values passed `errors`. */
  static changes(model: ConsoleModel, values: ModelFormValues): ModelChanges {
    const now = { name: values.name.trim(), label: values.label.trim(), ...ModelForm.settings(values) } as Record<string, unknown>;
    const was = model as unknown as Record<string, unknown>;
    const changed: Record<string, unknown> = {};
    for (const [field, value] of Object.entries(now)) {
      if (!ModelForm.same(field, value, was[field])) changed[field] = value;
    }
    return changed as ModelChanges;
  }

  static serverErrors(error: unknown): FormErrors<ModelFormValues> {
    return firstMessages(error);
  }

  /** The fields shared by a new model and an edit, as the API takes them. */
  private static settings(values: ModelFormValues) {
    const out: Record<string, unknown> = {
      context_window: Number(values.context_window.trim()),
      max_output_tokens: Number(values.max_output_tokens.trim()),
      rpm_limit: values.rpm_limit.trim() ? Number(values.rpm_limit.trim()) : null,
      input_cost_per_mtok: values.input_cost_per_mtok.trim() || null,
      output_cost_per_mtok: values.output_cost_per_mtok.trim() || null,
      default_params: params(values.default_params) ?? {},
    };
    for (const field of BOOLEANS) out[field] = values[field];
    for (const field of CHOICES) out[field] = values[field];
    return out;
  }

  private static same(field: string, now: unknown, was: unknown): boolean {
    if (field.endsWith("_cost_per_mtok")) {
      return now === null || was === null || was === undefined ? now === (was ?? null) : Number(now) === Number(was);
    }
    return canonical(now) === canonical(was);
  }

  /** "0.1500" is shown as "0.15". */
  private static priceText(price: string | null): string {
    return price === null ? "" : String(Number(price));
  }

  private static priceError(text: string): string | null {
    const trimmed = text.trim();
    if (!trimmed) return null;
    if (!/^\d+(\.\d+)?$/.test(trimmed)) return PRICE;
    if (/\.\d{5,}$/.test(trimmed)) return "Prices have at most 4 decimal places.";
    return Number(trimmed) >= 1_000_000 ? "Enter less than 1,000,000 dollars." : null;
  }
}

/** What the boxes of the provider form hold. */
export type ProviderFormValues = { rpm_limit: string; base_url: string; enabled: boolean };

/** The provider form: a rate limit, an address (only where the provider takes one) and a switch. Keys stay in the environment. */
export class ProviderForm {
  /** Kinds that are reached at an address of their own. The others have a fixed one, and the API refuses an address for them. */
  private static readonly ADDRESSED = new Set(["ollama", "openai_compatible"]);

  static takesBaseUrl(provider: Pick<ConsoleProvider, "kind">): boolean {
    return ProviderForm.ADDRESSED.has(provider.kind);
  }

  static fromProvider(provider: ConsoleProvider): ProviderFormValues {
    return { rpm_limit: provider.rpm_limit === null ? "" : String(provider.rpm_limit), base_url: provider.base_url, enabled: provider.enabled };
  }

  static errors(provider: ConsoleProvider, values: ProviderFormValues): FormErrors<ProviderFormValues> {
    const errors: FormErrors<ProviderFormValues> = {};
    if (values.rpm_limit.trim() && positive(values.rpm_limit) === null) errors.rpm_limit = LIMIT;
    if (ProviderForm.takesBaseUrl(provider) && !ProviderForm.isWebAddress(values.base_url)) {
      errors.base_url = "Enter the address, like http://localhost:11434.";
    }
    return errors;
  }

  static changes(provider: ConsoleProvider, values: ProviderFormValues): ProviderChanges {
    const changes: ProviderChanges = {};
    const limit = values.rpm_limit.trim() ? Number(values.rpm_limit.trim()) : null;
    if (limit !== provider.rpm_limit) changes.rpm_limit = limit;
    if (values.enabled !== provider.enabled) changes.enabled = values.enabled;
    if (ProviderForm.takesBaseUrl(provider) && values.base_url.trim() !== provider.base_url) changes.base_url = values.base_url.trim();
    return changes;
  }

  static serverErrors(error: unknown): FormErrors<ProviderFormValues> {
    return firstMessages(error);
  }

  private static isWebAddress(text: string): boolean {
    try {
      const url = new URL(text.trim());
      return (url.protocol === "http:" || url.protocol === "https:") && url.hostname !== "";
    } catch {
      return false;
    }
  }
}
