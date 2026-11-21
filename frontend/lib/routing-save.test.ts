/**
 * Unit under test: `RoutingSaver`, which saves the edited routing steps one request each and reports what happened.
 *
 * Why: the API replaces one step atomically, so saving several steps is several requests and some may succeed while
 * others are refused. If a refusal hid the saves that worked, the staff would redo them; if a success hid a refusal,
 * a lesson would run on routing nobody meant. Each step's outcome is therefore kept apart, with the API's reasons.
 *
 * Use cases:
 * - sends one PUT per step with that step's body, in the order given
 * - returns the API's saved version of each step that worked
 * - a refused step keeps its reasons and does not stop the others
 * - a step that fails without a reason from the API gets one calm sentence
 * - the toast says everything saved, or how many were saved and how many were not
 */
import { describe, expect, test } from "bun:test";

import { ApiError } from "./api";
import { RoutingDraft } from "./routing-draft";
import { RoutingSaver } from "./routing-save";
import type { NodeRouting, NodeRoutingInput } from "./types";

const node = (key: string): NodeRouting => ({
  key,
  phase: "build",
  description: "",
  optional: false,
  output: "text",
  requires: [],
  min_output_tokens: 0,
  min_context: 0,
  enabled: true,
  reasoning_effort: "low",
  max_attempts: 2,
  max_tool_steps: null,
  timeout_s: 60,
  params_override: {},
  bindings: [{ model: 1, model_label: "groq/a", enabled: true, max_retries: 2, overrides: { params: {}, reasoning_effort: "" }, problems: [] }],
});

function fake(refuse: Record<string, unknown> = {}) {
  const sent: [string, NodeRoutingInput][] = [];
  const api = {
    async saveNode(key: string, body: NodeRoutingInput): Promise<NodeRouting> {
      sent.push([key, body]);
      if (key in refuse) throw refuse[key];
      return { ...node(key), timeout_s: 999 };
    },
  };
  return { sent, saver: new RoutingSaver(api) };
}

describe("save", () => {
  test("sends one request per step with that step's body, in order", async () => {
    const { saver, sent } = fake();

    await saver.save([node("a"), node("b"), node("c")], ["c", "a"]);

    expect(sent.map(([key]) => key)).toEqual(["c", "a"]);
    expect(sent[0][1]).toEqual(RoutingDraft.input(node("c")));
  });

  test("returns the saved version of each step that worked", async () => {
    const { saver } = fake();

    const outcome = await saver.save([node("a")], ["a"]);

    expect(outcome.saved.map((n) => [n.key, n.timeout_s])).toEqual([["a", 999]]);
    expect(outcome.failed).toEqual({});
  });

  test("a refused step keeps the API's reasons and the others are still saved", async () => {
    const { saver } = fake({ a: new ApiError(400, "invalid", "x", { bindings: ["Model 1 (groq/a): no key."], timeout_s: ["Too small."] }) });

    const outcome = await saver.save([node("a"), node("b")], ["a", "b"]);

    expect(outcome.saved.map((n) => n.key)).toEqual(["b"]);
    expect(outcome.failed).toEqual({ a: ["Model 1 (groq/a): no key.", "Timeout: Too small."] });
  });

  test("a step that fails without a reason gets one calm sentence", async () => {
    const { saver } = fake({ a: new TypeError("fetch failed") });

    const outcome = await saver.save([node("a")], ["a"]);

    expect(outcome.failed.a).toEqual(["That did not work. Check the connection and try again."]);
  });

  test("a key with no step is reported, not sent", async () => {
    const { saver, sent } = fake();

    const outcome = await saver.save([node("a")], ["zzz"]);

    expect(sent).toEqual([]);
    expect(outcome.failed.zzz).toEqual(["That step is not on this page any more. Reload and try again."]);
  });
});

describe("message", () => {
  test("says all saved, or how many were saved and how many were not", () => {
    expect(RoutingSaver.message({ saved: [node("a")], failed: {} })).toBe("Routing saved. New lessons will use it.");
    expect(RoutingSaver.message({ saved: [node("a"), node("b")], failed: { c: ["x"] } })).toBe("Saved 2 steps. 1 could not be saved: see the notes on it.");
    expect(RoutingSaver.message({ saved: [], failed: { c: ["x"], d: ["y"] } })).toBe("Nothing was saved. 2 steps could not be saved: see the notes on them.");
  });
});
