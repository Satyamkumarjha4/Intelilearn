/**
 * Unit under test: `UsageFilterOptions`, the choices in the usage page's drop-downs and how one filter changes another.
 *
 * Why: the usage page filters by provider, model, step and outcome, all kept in the address. A model list that shows
 * models of another provider, a model left selected after its provider changed (an empty page with no explanation), or
 * a provider shown by a key nobody recognises would make the numbers look wrong when they are only filtered.
 *
 * Use cases:
 * - providers are offered by key (what the API filters on), named like the charts name them; an unknown one keeps its key
 * - models are offered by name once, sorted, and only those of the chosen provider when one is chosen
 * - steps keep the order they were given (lesson order)
 * - outcomes use the console's words: Worked, Worked after retry, Failed
 * - changing the provider clears a chosen model that does not belong to the new provider, and keeps one that does
 * - clearing the provider keeps the model; any other change leaves the filters alone
 */
import { describe, expect, test } from "bun:test";

import { UsageFilterOptions } from "./console-filters";

const models = [
  { name: "openai/gpt-oss-120b", provider: "groq" },
  { name: "gemini-3.5-flash", provider: "gemini" },
  { name: "gpt-oss-20b", provider: "groq" },
  { name: "gemini-3.5-flash", provider: "vertex" },
];

describe("UsageFilterOptions.providers", () => {
  test("offers the key as the value and the chart name as the label", () => {
    expect(UsageFilterOptions.providers([{ key: "groq" }, { key: "gemini" }, { key: "openai" }])).toEqual([
      { value: "groq", label: "Groq" },
      { value: "gemini", label: "Google" },
      { value: "openai", label: "OpenAI" },
    ]);
  });

  test("an unknown provider is shown by its key", () => {
    expect(UsageFilterOptions.providers([{ key: "mistral" }])).toEqual([{ value: "mistral", label: "mistral" }]);
  });
});

describe("UsageFilterOptions.models", () => {
  test("lists each model name once, sorted, when no provider is chosen", () => {
    expect(UsageFilterOptions.models(models, "").map((o) => o.value)).toEqual(["gemini-3.5-flash", "gpt-oss-20b", "openai/gpt-oss-120b"]);
  });

  test("lists only the chosen provider's models", () => {
    expect(UsageFilterOptions.models(models, "groq").map((o) => o.value)).toEqual(["gpt-oss-20b", "openai/gpt-oss-120b"]);
    expect(UsageFilterOptions.models(models, "nobody")).toEqual([]);
  });
});

describe("UsageFilterOptions.steps and outcomes", () => {
  test("steps keep their order", () => {
    expect(UsageFilterOptions.steps(["lesson.plan", "page.compile", "diagnostic.generate"])).toEqual([
      { value: "lesson.plan" },
      { value: "page.compile" },
      { value: "diagnostic.generate" },
    ]);
  });

  test("outcomes are named the way the page names them", () => {
    expect(UsageFilterOptions.outcomes()).toEqual([
      { value: "ok", label: "Worked" },
      { value: "retried", label: "Worked after retry" },
      { value: "failed", label: "Failed" },
    ]);
  });
});

describe("UsageFilterOptions.change", () => {
  test("a new provider clears a model that is not its own", () => {
    const next = UsageFilterOptions.change({ range: "7d", provider: "groq", model: "gpt-oss-20b" }, { provider: "gemini" }, models);
    expect(next).toEqual({ range: "7d", provider: "gemini", model: "" });
  });

  test("a new provider keeps a model it also serves", () => {
    const next = UsageFilterOptions.change({ provider: "gemini", model: "gemini-3.5-flash" }, { provider: "vertex" }, models);
    expect(next.model).toBe("gemini-3.5-flash");
  });

  test("clearing the provider keeps the model, and other changes touch nothing else", () => {
    expect(UsageFilterOptions.change({ provider: "groq", model: "gpt-oss-20b" }, { provider: "" }, models).model).toBe("gpt-oss-20b");
    expect(UsageFilterOptions.change({ provider: "groq", model: "gpt-oss-20b" }, { node: "lesson.plan" }, models)).toEqual({
      provider: "groq",
      model: "gpt-oss-20b",
      node: "lesson.plan",
    });
  });
});
