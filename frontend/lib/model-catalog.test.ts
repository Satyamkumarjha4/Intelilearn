/**
 * Unit under test: `ModelCatalog`, the words and marks of the Models page (provider cards and the models table).
 *
 * Why: the page answers "can I use this model right now?" in a glance. A provider that says "Key set" when the key is
 * missing, a context window of 131072 shown as "131.1k", a failed test shown without its reason, or a delete refusal
 * that does not name the steps that use the model, would each send the staff to look in the wrong place.
 *
 * Use cases:
 * - lists the models by provider, then by name, so one provider's models sit together
 * - names a provider and gives it its fixed colour (the same colour as on the usage charts)
 * - says whether the provider's key is set, and whether it is switched off
 * - writes the rate limit, the models count and the 7-day spend of a provider card
 * - lists what a model can do (JSON, tools, vision, reasoning)
 * - writes the context window, the prices per million tokens and the limit for the table
 * - says how the last test went (works with its time, failed with its reason, never tested, or no key)
 * - keeps a fresh test result on its row without asking the server again
 * - explains a delete refused because steps still use the model
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { ModelCatalog } from "./model-catalog";
import type { ConsoleModel, ConsoleProvider } from "./types";

const provider = (extra: Partial<ConsoleProvider> = {}): ConsoleProvider => ({
  key: "groq",
  kind: "groq",
  api_key_env: "GROQ_API_KEY",
  api_key_set: true,
  base_url: "",
  rpm_limit: 30,
  enabled: true,
  models_count: 2,
  spend_7d: "1.123456",
  ...extra,
});

const model = (extra: Partial<ConsoleModel> = {}): ConsoleModel =>
  ({
    id: 1,
    provider: "groq",
    name: "gpt-oss-120b",
    enabled: true,
    api_key_set: true,
    supports_structured_output: true,
    supports_tool_calling: true,
    supports_vision: false,
    supports_reasoning: false,
    context_window: 131072,
    rpm_limit: 30,
    input_cost_per_mtok: "0.1500",
    output_cost_per_mtok: "0.6000",
    last_probe: null,
    ...extra,
  }) as ConsoleModel;

const NOW = new Date("2026-03-15T12:00:00Z");

describe("sorted", () => {
  test("puts one provider's models together, by provider name and then display name, without changing the list it is given", () => {
    const rows = [
      model({ id: 1, provider: "gemini", name: "g-2", label: "Gemini B" }),
      model({ id: 2, provider: "groq", name: "q-1", label: "" }),
      model({ id: 3, provider: "gemini", name: "g-1", label: "Gemini A" }),
      model({ id: 4, provider: "groq", name: "a-1", label: "" }),
    ];

    expect(ModelCatalog.sorted(rows).map((m) => m.id)).toEqual([3, 1, 4, 2]);
    expect(rows.map((m) => m.id)).toEqual([1, 2, 3, 4]);
  });
});

describe("provider names and colours", () => {
  test.each([
    ["groq", "Groq", "var(--chart-cat-1)"],
    ["gemini", "Google", "var(--chart-cat-2)"],
    ["openai", "OpenAI", "var(--chart-cat-3)"],
    ["ollama", "Ollama", "var(--chart-cat-other)"],
    ["my_lab", "My lab", "var(--chart-cat-other)"],
  ])("%s is %s", (key, name, color) => {
    expect(ModelCatalog.providerName(key)).toBe(name);
    expect(ModelCatalog.swatch(key)).toBe(color);
  });
});

describe("providerCard", () => {
  test("a provider with its key set reads as ready, with its limit, models and spend", () => {
    expect(ModelCatalog.providerCard(provider())).toEqual({
      name: "Groq",
      swatch: "var(--chart-cat-1)",
      status: { tone: "ok", label: "Key set" },
      secret: "GROQ_API_KEY",
      rows: [["Rate limit", "30 / min"], ["Models", "2"], ["Spend (7 d)", "$1.12"]],
    });
  });

  test("a missing key says so", () => {
    expect(ModelCatalog.providerCard(provider({ api_key_set: false })).status).toEqual({ tone: "bad", label: "Key missing" });
  });

  test("a provider that is switched off says that first, whatever its key", () => {
    expect(ModelCatalog.providerCard(provider({ enabled: false })).status).toEqual({ tone: "off", label: "Disabled" });
    expect(ModelCatalog.providerCard(provider({ enabled: false, api_key_set: false })).status.label).toBe("Disabled");
  });

  test("a provider with no key to set (a local one) shows its address instead of a variable", () => {
    const card = ModelCatalog.providerCard(provider({ key: "ollama", kind: "ollama", api_key_env: "", api_key_set: true, base_url: "http://localhost:11434", rpm_limit: null }));

    expect(card.secret).toBe("http://localhost:11434");
    expect(card.rows[0]).toEqual(["Rate limit", "none"]);
    expect(card.status.label).toBe("No key needed");
  });

  test("no spend reads as free for a provider that costs nothing and $0.00 otherwise", () => {
    expect(ModelCatalog.providerCard(provider({ spend_7d: "0" })).rows[2]).toEqual(["Spend (7 d)", "$0.00"]);
    expect(ModelCatalog.providerCard(provider({ kind: "ollama", api_key_env: "", spend_7d: "0" })).rows[2]).toEqual(["Spend (7 d)", "free"]);
  });
});

describe("capabilities", () => {
  test("lists what the model can do, in a fixed order", () => {
    expect(ModelCatalog.capabilities(model())).toEqual(["JSON", "Tools"]);
    expect(ModelCatalog.capabilities(model({ supports_vision: true, supports_reasoning: true }))).toEqual(["JSON", "Tools", "Vision", "Reasoning"]);
    expect(ModelCatalog.capabilities(model({ supports_structured_output: false, supports_tool_calling: false }))).toEqual([]);
  });
});

describe("table text", () => {
  test.each([
    [131072, "131k"],
    [400000, "400k"],
    [8192, "8k"],
    [1000000, "1M"],
    [1048576, "1M"],
    [2000000, "2M"],
    [500, "500"],
  ])("a context window of %i is %s", (tokens, text) => {
    expect(ModelCatalog.context(tokens)).toBe(text);
  });

  test.each([
    ["0.1500", "0.15"],
    ["0.0750", "0.075"],
    ["2.5000", "2.50"],
    ["0.6000", "0.60"],
    ["0", "free"],
    [null, "–"],
  ])("a price of %s per million tokens is %s", (price, text) => {
    expect(ModelCatalog.price(price)).toBe(text);
  });

  test("the limit is per minute, or a dash when there is none", () => {
    expect(ModelCatalog.limit(30)).toBe("30/min");
    expect(ModelCatalog.limit(null)).toBe("–");
  });
});

describe("lastTest", () => {
  test("a test that worked says so with its time and how long ago", () => {
    const test = ModelCatalog.lastTest(model({ last_probe: { at: "2026-03-15T10:00:00Z", ok: true, latency_s: 1.94, error: "" } }), NOW);

    expect(test).toEqual({ state: "ok", label: "Works", detail: "1.9 s", when: "2 h ago" });
  });

  test("a test that failed says why", () => {
    const test = ModelCatalog.lastTest(model({ last_probe: { at: "2026-03-15T11:30:00Z", ok: false, latency_s: null, error: "structured_output: invalid JSON" } }), NOW);

    expect(test).toEqual({ state: "bad", label: "Failed", detail: "structured_output: invalid JSON", when: "30 min ago" });
  });

  test("a long reason is cut short for the table, whole in the title", () => {
    const error = "x".repeat(300);
    const test = ModelCatalog.lastTest(model({ last_probe: { at: "2026-03-15T11:30:00Z", ok: false, latency_s: null, error } }), NOW);

    expect(test.detail.length).toBeLessThanOrEqual(80);
    expect(test.detail.endsWith("…")).toBe(true);
    expect(test.title).toBe(error);
  });

  test("a model whose provider has no key cannot be tested", () => {
    expect(ModelCatalog.lastTest(model({ api_key_set: false }), NOW)).toMatchObject({ state: "nokey", label: "No key" });
  });

  test("a model that is switched off cannot be tested either", () => {
    expect(ModelCatalog.lastTest(model({ enabled: false }), NOW)).toMatchObject({ state: "off", label: "Switched off" });
  });

  test("a model never tested says so", () => {
    expect(ModelCatalog.lastTest(model(), NOW)).toMatchObject({ state: "never", label: "Not tested yet" });
  });

  test("canTest is false without a key or when it is off", () => {
    expect(ModelCatalog.canTest(model())).toBe(true);
    expect(ModelCatalog.canTest(model({ api_key_set: false }))).toBe(false);
    expect(ModelCatalog.canTest(model({ enabled: false }))).toBe(false);
  });
});

describe("withProbe", () => {
  test("keeps the result on the row, as the server keeps it", () => {
    const row = ModelCatalog.withProbe(model(), { ok: false, latency_s: null, error: "capability: nope", checks: [] }, NOW);

    expect(row.last_probe).toEqual({ at: "2026-03-15T12:00:00.000Z", ok: false, latency_s: null, error: "capability: nope" });
  });

  test("a null error becomes an empty one", () => {
    expect(ModelCatalog.withProbe(model(), { ok: true, latency_s: 1, error: null, checks: [] }, NOW).last_probe?.error).toBe("");
  });
});

describe("inUse", () => {
  test("names the steps that use the model", () => {
    const error = new ApiError(409, "model_in_use", "x", {}, { nodes: ["lesson.plan", "page.generate"] });

    expect(ModelCatalog.inUse(error)).toBe("Used by: lesson.plan, page.generate. Take it out of those steps in Model routing first.");
  });

  test("is null for any other failure", () => {
    expect(ModelCatalog.inUse(new ApiError(409, "other", "x"))).toBeNull();
    expect(ModelCatalog.inUse(new ApiError(400, "invalid", "x"))).toBeNull();
    expect(ModelCatalog.inUse(new Error("x"))).toBeNull();
  });
});
