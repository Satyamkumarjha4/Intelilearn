/**
 * Unit under test: `ModelForm` and `ProviderForm`, the forms behind "Add model", "Edit model" and "Edit provider".
 *
 * Why: the registry decides what every lesson step can call, so a wrong number here is a model that is never used (a
 * context window of 0), billed wrongly (a price typed with a comma) or unreachable (a bad address). The API checks
 * all of it, but its answer comes after a round trip; checking first tells the staff what is wrong beside the box, and
 * the patch sends only what was changed so an edit of one field cannot overwrite another person's edit of a second.
 *
 * Use cases (ModelForm):
 * - starts a new model with the registry's own defaults, and an existing one from its saved values
 * - requires a name and a provider (a new model), whole numbers where the model needs them, and prices as dollars
 * - allows a blank limit and blank prices, and says so by sending null
 * - requires the default parameters to be a JSON object
 * - requires a reasoning control for a reasoning model
 * - sends everything for a new model, and only what changed for an edit
 * - turns the API's refusal into a message per field
 * Use cases (ProviderForm):
 * - starts from the provider's limit, address and switch; a blank limit means no limit
 * - asks for an address only where the provider takes one, and checks that it is a web address
 * - sends only what changed
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { ModelForm, ProviderForm } from "./model-form";
import type { ConsoleModel, ConsoleProvider } from "./types";

const model: ConsoleModel = {
  id: 5,
  provider: "groq",
  name: "gpt-oss-120b",
  label: "GPT OSS 120B",
  enabled: true,
  api_key_set: true,
  default_params: { temperature: 0.4 },
  supports_structured_output: true,
  structured_output_method: "json_schema",
  supports_tool_calling: true,
  supports_parallel_tool_calls: false,
  supports_vision: false,
  supports_reasoning: false,
  reasoning_control: "none",
  reasoning_disables_sampling: false,
  context_window: 131072,
  max_output_tokens: 8192,
  rpm_limit: 30,
  input_cost_per_mtok: "0.1500",
  output_cost_per_mtok: "0.6000",
  bound_nodes: [],
  last_probe: null,
};

describe("ModelForm values", () => {
  test("a new model starts with the registry's defaults and the chosen provider", () => {
    const values = ModelForm.blank("groq");

    expect(values).toMatchObject({ provider: "groq", name: "", label: "", enabled: true, context_window: "128000", max_output_tokens: "8192", rpm_limit: "", input_cost_per_mtok: "", output_cost_per_mtok: "", structured_output_method: "json_schema", reasoning_control: "none", default_params: "{}" });
    expect(values.supports_structured_output).toBe(false);
  });

  test("an existing model starts from what is saved, as text", () => {
    const values = ModelForm.fromModel(model);

    expect(values).toMatchObject({ name: "gpt-oss-120b", context_window: "131072", rpm_limit: "30", input_cost_per_mtok: "0.15", output_cost_per_mtok: "0.6", default_params: '{\n  "temperature": 0.4\n}' });
  });

  test("a model with no limit or prices starts with empty boxes", () => {
    const values = ModelForm.fromModel({ ...model, rpm_limit: null, input_cost_per_mtok: null, output_cost_per_mtok: null, default_params: {} });

    expect(values).toMatchObject({ rpm_limit: "", input_cost_per_mtok: "", output_cost_per_mtok: "", default_params: "{}" });
  });
});

describe("ModelForm errors", () => {
  const good = ModelForm.fromModel(model);

  test("a saved model has none", () => {
    expect(ModelForm.errors(good, "edit")).toEqual({});
  });

  test("a name is needed, and a provider for a new model only", () => {
    expect(ModelForm.errors({ ...good, name: "  " }, "edit").name).toBe("Enter the model id the provider uses.");
    expect(ModelForm.errors({ ...good, provider: "" }, "add").provider).toBe("Choose a provider.");
    expect(ModelForm.errors({ ...good, provider: "" }, "edit").provider).toBeUndefined();
    expect(ModelForm.errors({ ...good, name: "x".repeat(151) }, "edit").name).toBe("At most 150 characters.");
  });

  test.each([
    ["context_window", "", "Enter a whole number, 1 or more."],
    ["context_window", "0", "Enter a whole number, 1 or more."],
    ["context_window", "12.5", "Enter a whole number, 1 or more."],
    ["max_output_tokens", "abc", "Enter a whole number, 1 or more."],
    ["rpm_limit", "0", "Leave blank for no limit, or enter a whole number, 1 or more."],
    ["rpm_limit", "x", "Leave blank for no limit, or enter a whole number, 1 or more."],
    ["input_cost_per_mtok", "-1", "Enter dollars per million tokens, like 0.15, or leave blank."],
    ["input_cost_per_mtok", "0,15", "Enter dollars per million tokens, like 0.15, or leave blank."],
    ["output_cost_per_mtok", "$2", "Enter dollars per million tokens, like 0.15, or leave blank."],
    ["output_cost_per_mtok", "0.12345", "Prices have at most 4 decimal places."],
    ["output_cost_per_mtok", "1000000", "Enter less than 1,000,000 dollars."],
  ])("%s = %j: %s", (field, text, message) => {
    expect(ModelForm.errors({ ...good, [field]: text }, "edit")[field as keyof typeof good]).toBe(message);
  });

  test("blank limit and prices are fine, and so is a price of 0", () => {
    expect(ModelForm.errors({ ...good, rpm_limit: "", input_cost_per_mtok: "", output_cost_per_mtok: "0" }, "edit")).toEqual({});
  });

  test("the default parameters must be a JSON object", () => {
    expect(ModelForm.errors({ ...good, default_params: "{" }, "edit").default_params).toBe("Enter a JSON object like {\"temperature\": 0.4}.");
    expect(ModelForm.errors({ ...good, default_params: "[1]" }, "edit").default_params).toBe("Enter a JSON object like {\"temperature\": 0.4}.");
    expect(ModelForm.errors({ ...good, default_params: "null" }, "edit").default_params).toBeDefined();
    expect(ModelForm.errors({ ...good, default_params: "" }, "edit")).toEqual({});
    expect(ModelForm.errors({ ...good, default_params: "{}" }, "edit")).toEqual({});
  });

  test("a reasoning model needs a way to control reasoning", () => {
    const errors = ModelForm.errors({ ...good, supports_reasoning: true, reasoning_control: "none" }, "edit");

    expect(errors.reasoning_control).toBe("Choose how reasoning is controlled for a reasoning model.");
    expect(ModelForm.errors({ ...good, supports_reasoning: true, reasoning_control: "effort" }, "edit")).toEqual({});
  });
});

describe("ModelForm payloads", () => {
  test("a new model sends everything, with numbers as numbers and blanks as null", () => {
    const values = { ...ModelForm.blank("groq"), name: " new-model ", rpm_limit: "", input_cost_per_mtok: "0.3", supports_structured_output: true, default_params: "" };

    expect(ModelForm.newModel(values)).toMatchObject({
      provider: "groq",
      name: "new-model",
      enabled: true,
      context_window: 128000,
      max_output_tokens: 8192,
      rpm_limit: null,
      input_cost_per_mtok: "0.3",
      output_cost_per_mtok: null,
      supports_structured_output: true,
      default_params: {},
    });
  });

  test("an edit sends only what changed", () => {
    const values = { ...ModelForm.fromModel(model), label: "New name", context_window: "200000", supports_vision: true };

    expect(ModelForm.changes(model, values)).toEqual({ label: "New name", context_window: 200000, supports_vision: true });
  });

  test("nothing changed sends nothing, and a price typed another way is not a change", () => {
    expect(ModelForm.changes(model, ModelForm.fromModel(model))).toEqual({});
    expect(ModelForm.changes(model, { ...ModelForm.fromModel(model), input_cost_per_mtok: "0.150" })).toEqual({});
    expect(ModelForm.changes(model, { ...ModelForm.fromModel(model), default_params: '{"temperature":0.4}' })).toEqual({});
  });

  test("clearing the limit or a price sends null", () => {
    expect(ModelForm.changes(model, { ...ModelForm.fromModel(model), rpm_limit: "", output_cost_per_mtok: "" })).toEqual({ rpm_limit: null, output_cost_per_mtok: null });
  });

  test("changed default parameters are sent as an object", () => {
    expect(ModelForm.changes(model, { ...ModelForm.fromModel(model), default_params: '{"temperature": 0.9}' })).toEqual({ default_params: { temperature: 0.9 } });
  });

  test("the API's refusal is a message per field", () => {
    const error = new ApiError(400, "invalid", "x", { name: ["A model with this name already exists for this provider."], default_params: ["bad", "worse"] });

    expect(ModelForm.serverErrors(error)).toEqual({ name: "A model with this name already exists for this provider.", default_params: "bad" });
    expect(ModelForm.serverErrors(new TypeError("offline"))).toEqual({});
  });
});

const provider: ConsoleProvider = { key: "groq", kind: "groq", api_key_env: "GROQ_API_KEY", api_key_set: true, base_url: "", rpm_limit: 30, enabled: true, models_count: 2, spend_7d: "0" };
const local: ConsoleProvider = { ...provider, key: "ollama", kind: "ollama", api_key_env: "", base_url: "http://localhost:11434", rpm_limit: null };

describe("ProviderForm", () => {
  test("starts from the provider's limit, address and switch", () => {
    expect(ProviderForm.fromProvider(provider)).toEqual({ rpm_limit: "30", base_url: "", enabled: true });
    expect(ProviderForm.fromProvider(local)).toEqual({ rpm_limit: "", base_url: "http://localhost:11434", enabled: true });
  });

  test("only some kinds take an address", () => {
    expect(ProviderForm.takesBaseUrl(local)).toBe(true);
    expect(ProviderForm.takesBaseUrl({ ...provider, kind: "openai_compatible" })).toBe(true);
    expect(ProviderForm.takesBaseUrl(provider)).toBe(false);
  });

  test("a limit is blank or a whole number, 1 or more", () => {
    const values = ProviderForm.fromProvider(provider);

    expect(ProviderForm.errors(provider, { ...values, rpm_limit: "" })).toEqual({});
    expect(ProviderForm.errors(provider, { ...values, rpm_limit: "0" }).rpm_limit).toBe("Leave blank for no limit, or enter a whole number, 1 or more.");
    expect(ProviderForm.errors(provider, { ...values, rpm_limit: "1.5" }).rpm_limit).toBeDefined();
  });

  test("a provider that takes an address needs a web address", () => {
    const values = ProviderForm.fromProvider(local);

    expect(ProviderForm.errors(local, values)).toEqual({});
    expect(ProviderForm.errors(local, { ...values, base_url: "" }).base_url).toBe("Enter the address, like http://localhost:11434.");
    expect(ProviderForm.errors(local, { ...values, base_url: "localhost:11434" }).base_url).toBe("Enter the address, like http://localhost:11434.");
    expect(ProviderForm.errors(local, { ...values, base_url: "ftp://x" }).base_url).toBeDefined();
    expect(ProviderForm.errors(local, { ...values, base_url: "https://models.example.com/v1" })).toEqual({});
  });

  test("a provider that takes no address is not asked for one", () => {
    expect(ProviderForm.errors(provider, { ...ProviderForm.fromProvider(provider), base_url: "" })).toEqual({});
  });

  test("sends only what changed; a blank limit is null; an address only where it is taken", () => {
    const values = ProviderForm.fromProvider(provider);

    expect(ProviderForm.changes(provider, values)).toEqual({});
    expect(ProviderForm.changes(provider, { ...values, rpm_limit: "", enabled: false })).toEqual({ rpm_limit: null, enabled: false });
    expect(ProviderForm.changes(provider, { ...values, base_url: "http://x" })).toEqual({});
    expect(ProviderForm.changes(local, { ...ProviderForm.fromProvider(local), base_url: " http://other:1 " })).toEqual({ base_url: "http://other:1" });
  });

  test("the API's refusal is a message per field", () => {
    expect(ProviderForm.serverErrors(new ApiError(400, "invalid", "x", { base_url: ["Required."] }))).toEqual({ base_url: "Required." });
  });
});
