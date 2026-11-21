import { ApiError } from "@/lib/api";
import { ProviderSeries } from "@/lib/console-charts";
import { ConsoleFormat } from "@/lib/console-format";
import { RunText } from "@/lib/run-text";
import type { ConsoleModel, ConsoleProvider, ProbeResult } from "@/lib/types";

/** The tones a provider card uses; the console's status pill knows all of them. */
export type ProviderTone = "ok" | "bad" | "off";
export type ProviderCard = {
  name: string;
  swatch: string;
  status: { tone: ProviderTone; label: string };
  /** The environment variable that holds the key, or the address of a provider that needs no key. */
  secret: string;
  rows: [label: string, value: string][];
};
export type TestState = "ok" | "bad" | "never" | "nokey" | "off";
export type LastTest = { state: TestState; label: string; detail: string; when: string; title?: string };

const NAMES: Record<string, string> = { groq: "Groq", gemini: "Google", google: "Google", google_genai: "Google", openai: "OpenAI", anthropic: "Anthropic", ollama: "Ollama", mistral: "Mistral" };
const REASON_LENGTH = 80;

/** The words and marks of the Models page. A provider keeps one colour here and on the usage charts. */
export class ModelCatalog {
  static providerName(key: string): string {
    const known = NAMES[key.toLowerCase()];
    if (known) return known;
    const spaced = key.replace(/[_-]+/g, " ").trim();
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  }

  /** By provider (as it is named), then by the name shown for the model. */
  static sorted(models: readonly ConsoleModel[]): ConsoleModel[] {
    const shown = (model: ConsoleModel) => (model.label || model.name).toLowerCase();
    return [...models].sort(
      (a, b) =>
        ModelCatalog.providerName(a.provider).localeCompare(ModelCatalog.providerName(b.provider)) || shown(a).localeCompare(shown(b)),
    );
  }

  static swatch(providerKey: string): string {
    return ProviderSeries.color(ProviderSeries.of(providerKey));
  }

  static providerCard(provider: ConsoleProvider): ProviderCard {
    const local = !provider.api_key_env;
    return {
      name: ModelCatalog.providerName(provider.key),
      swatch: ModelCatalog.swatch(provider.key),
      status: ModelCatalog.providerStatus(provider, local),
      secret: local ? provider.base_url : provider.api_key_env,
      rows: [
        ["Rate limit", provider.rpm_limit ? `${provider.rpm_limit} / min` : "none"],
        ["Models", String(provider.models_count)],
        ["Spend (7 d)", local && Number(provider.spend_7d) === 0 ? "free" : ConsoleFormat.money(provider.spend_7d)],
      ],
    };
  }

  /** What the model can do, in a fixed order. */
  static capabilities(model: ConsoleModel): string[] {
    const flags: [boolean, string][] = [
      [model.supports_structured_output, "JSON"],
      [model.supports_tool_calling, "Tools"],
      [model.supports_vision, "Vision"],
      [model.supports_reasoning, "Reasoning"],
    ];
    return flags.filter(([on]) => on).map(([, label]) => label);
  }

  /** "131k", "1M": a window is read in thousands of tokens. */
  static context(tokens: number): string {
    if (tokens >= 1_000_000) return `${Number((tokens / 1_000_000).toFixed(1))}M`;
    return tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens);
  }

  /** Dollars per million tokens: two places, a third where it is needed ("0.075"); "free"; a dash when not set. */
  static price(perMtok: string | null): string {
    if (perMtok === null || perMtok === "") return "–";
    const amount = Number(perMtok);
    if (Number.isNaN(amount)) return "–";
    if (amount === 0) return "free";
    const places = Math.round(amount * 1000) % 10 === 0 ? 2 : 3;
    return amount.toFixed(places);
  }

  static limit(rpm: number | null): string {
    return rpm ? `${rpm}/min` : "–";
  }

  /** A model can be tested when its provider has a key and it is switched on. */
  static canTest(model: Pick<ConsoleModel, "api_key_set" | "enabled">): boolean {
    return model.api_key_set && model.enabled;
  }

  static lastTest(model: ConsoleModel, now: Date): LastTest {
    if (!model.api_key_set) return { state: "nokey", label: "No key", detail: "", when: "" };
    if (!model.enabled) return { state: "off", label: "Switched off", detail: "", when: "" };
    const probe = model.last_probe;
    if (!probe) return { state: "never", label: "Not tested yet", detail: "", when: "" };
    const when = RunText.ago(probe.at, now);
    if (probe.ok) return { state: "ok", label: "Works", detail: probe.latency_s === null ? "" : ConsoleFormat.duration(probe.latency_s), when };
    const reason = probe.error || "no reason given";
    const short = reason.length > REASON_LENGTH ? `${reason.slice(0, REASON_LENGTH - 1)}…` : reason;
    return { state: "bad", label: "Failed", detail: short, when, ...(short !== reason ? { title: reason } : {}) };
  }

  /** The row with a fresh test result on it, as the server keeps it, so the table need not ask again. */
  static withProbe(model: ConsoleModel, result: ProbeResult, now: Date): ConsoleModel {
    return { ...model, last_probe: { at: now.toISOString(), ok: result.ok, latency_s: result.latency_s, error: result.error ?? "" } };
  }

  /** The reason a delete was refused, when it was because steps still use the model; null for any other failure. */
  static inUse(error: unknown): string | null {
    if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "model_in_use") return null;
    const nodes = Array.isArray(error.extra.nodes) ? (error.extra.nodes as string[]) : [];
    return nodes.length ? `Used by: ${nodes.join(", ")}. Take it out of those steps in Model routing first.` : error.message;
  }

  private static providerStatus(provider: ConsoleProvider, local: boolean): ProviderCard["status"] {
    if (!provider.enabled) return { tone: "off", label: "Disabled" };
    if (local) return { tone: "ok", label: "No key needed" };
    return provider.api_key_set ? { tone: "ok", label: "Key set" } : { tone: "bad", label: "Key missing" };
  }
}
