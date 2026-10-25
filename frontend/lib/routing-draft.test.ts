/**
 * Unit under test: `RoutingDraft`, the console's local edits to the model routing (nothing is sent until Save).
 *
 * Why: the routing page keeps a copy of every step that the editor changes, and a Save sends only the steps that
 * really differ. A diff that counts a reordered chain as "no change", or that notices the API's derived `problems`
 * as an edit, either loses a change or offers a Save that does nothing. The chain's order is the priority, so a
 * reorder that drops or duplicates a model sends lessons to the wrong one.
 *
 * Use cases:
 * - turns a step into the body of `PUT /console/nodes/{key}` (chain order kept, derived fields left out)
 * - finds the steps that differ from what was saved: an identical copy is clean, derived `problems` do not count,
 *   and a reorder, a removal, an effort change or a switch counts
 * - reorders the chain by dragging (index to index), moves a model up, removes one but never the last, adds one
 * - lists the models that can be added as a fallback: switched on, provider key set, not already in the chain
 * - names the changed steps for the save bar
 * - lists the steps of the API's grouped routing in the order of the page, and puts saved steps back into it
 */
import { describe, expect, test } from "bun:test";

import { RoutingDraft } from "./routing-draft";
import type { ConsoleModel, ConsoleRouting, NodeRouting, RoutingBinding } from "./types";

const binding = (model: number, label = `groq/m${model}`, extra: Partial<RoutingBinding> = {}): RoutingBinding => ({
  model,
  model_label: label,
  enabled: true,
  max_retries: 2,
  overrides: { params: {}, reasoning_effort: "" },
  problems: [],
  ...extra,
});

const node = (key: string, ids: number[], extra: Partial<NodeRouting> = {}): NodeRouting => ({
  key,
  phase: "author",
  description: "",
  optional: false,
  output: "structured",
  requires: [],
  min_output_tokens: 0,
  min_context: 0,
  enabled: true,
  reasoning_effort: "medium",
  max_attempts: 3,
  max_tool_steps: null,
  timeout_s: 120,
  params_override: {},
  bindings: ids.map((id) => binding(id)),
  ...extra,
});

const model = (id: number, extra: Partial<ConsoleModel> = {}): ConsoleModel =>
  ({ id, provider: "groq", name: `m${id}`, enabled: true, api_key_set: true, ...extra }) as ConsoleModel;

describe("input", () => {
  test("is the PUT body, with the chain in priority order and no derived fields", () => {
    const body = RoutingDraft.input(node("lesson.plan", [3, 1], { max_tool_steps: 4, params_override: { top_p: 0.5 } }));

    expect(body).toEqual({
      enabled: true,
      reasoning_effort: "medium",
      max_attempts: 3,
      max_tool_steps: 4,
      timeout_s: 120,
      params_override: { top_p: 0.5 },
      bindings: [
        { model: 3, enabled: true, max_retries: 2, overrides: { params: {}, reasoning_effort: "" } },
        { model: 1, enabled: true, max_retries: 2, overrides: { params: {}, reasoning_effort: "" } },
      ],
    });
  });
});

describe("changed", () => {
  const saved = [node("a", [1, 2]), node("b", [1]), node("c", [2, 1])];

  test("an identical copy is clean, whatever the API says about problems", () => {
    const copy = saved.map((n) => ({ ...n, bindings: n.bindings.map((b) => ({ ...b, problems: ["no key"] })) }));

    expect(RoutingDraft.changed(saved, copy)).toEqual([]);
  });

  test("names the steps that differ, in the order of the page", () => {
    const edited = [
      { ...saved[0], bindings: [saved[0].bindings[1], saved[0].bindings[0]] },
      saved[1],
      { ...saved[2], reasoning_effort: "high" as const },
    ];

    expect(RoutingDraft.changed(saved, edited)).toEqual(["a", "c"]);
  });

  test.each([
    ["switching a step off", { enabled: false }],
    ["the attempts", { max_attempts: 4 }],
    ["the timeout", { timeout_s: 30 }],
    ["the step limit", { max_tool_steps: 2 }],
    ["a parameter", { params_override: { top_p: 1 } }],
  ])("%s counts as a change", (_name, patch) => {
    expect(RoutingDraft.changed([saved[0]], [{ ...saved[0], ...patch }])).toEqual(["a"]);
  });

  test("a change inside a binding counts", () => {
    const retries = { ...saved[1], bindings: [{ ...saved[1].bindings[0], max_retries: 5 }] };
    const parked = { ...saved[1], bindings: [{ ...saved[1].bindings[0], enabled: false }] };

    expect(RoutingDraft.changed([saved[1]], [retries])).toEqual(["b"]);
    expect(RoutingDraft.changed([saved[1]], [parked])).toEqual(["b"]);
  });

  test("a step missing from the copy is not counted as changed", () => {
    expect(RoutingDraft.changed(saved, [saved[0]])).toEqual([]);
  });
});

describe("editing the chain", () => {
  const start = node("a", [1, 2, 3]);
  const ids = (n: NodeRouting) => n.bindings.map((b) => b.model);

  test("reorder moves a model from one place to another", () => {
    expect(ids(RoutingDraft.reorder(start, 0, 2))).toEqual([2, 3, 1]);
    expect(ids(RoutingDraft.reorder(start, 2, 0))).toEqual([3, 1, 2]);
  });

  test("reorder with the same place, or a place outside the chain, changes nothing", () => {
    expect(RoutingDraft.reorder(start, 1, 1)).toBe(start);
    expect(RoutingDraft.reorder(start, 1, 7)).toBe(start);
    expect(RoutingDraft.reorder(start, -1, 0)).toBe(start);
  });

  test("moveUp swaps with the one above; the first cannot go up", () => {
    expect(ids(RoutingDraft.moveUp(start, 2))).toEqual([1, 3, 2]);
    expect(RoutingDraft.moveUp(start, 0)).toBe(start);
  });

  test("remove drops a model, but never the last one", () => {
    expect(ids(RoutingDraft.remove(start, 1))).toEqual([1, 3]);
    const one = node("a", [9]);
    expect(RoutingDraft.remove(one, 0)).toBe(one);
    expect(RoutingDraft.canRemove(one)).toBe(false);
    expect(RoutingDraft.canRemove(start)).toBe(true);
  });

  test("add puts a model last, switched on, with the usual retries", () => {
    const added = RoutingDraft.add(start, model(7, { name: "big", provider: "google" }));

    expect(ids(added)).toEqual([1, 2, 3, 7]);
    expect(added.bindings[3]).toMatchObject({ model: 7, model_label: "google/big", enabled: true, max_retries: 2, problems: [] });
  });

  test("editing never changes the original", () => {
    RoutingDraft.remove(start, 0);
    RoutingDraft.add(start, model(7));

    expect(ids(start)).toEqual([1, 2, 3]);
  });
});

describe("fallbacks", () => {
  test("offers only models that are on, have a key and are not in the chain yet", () => {
    const models = [model(1), model(2, { enabled: false }), model(3, { api_key_set: false }), model(4)];

    expect(RoutingDraft.fallbacks(node("a", [1]), models).map((m) => m.id)).toEqual([4]);
  });
});

describe("summary", () => {
  test("lists the changed steps for the save bar", () => {
    expect(RoutingDraft.summary(["a", "b"])).toBe("a, b");
    expect(RoutingDraft.summary([])).toBe("");
  });
});

describe("grouped routing", () => {
  const routing: ConsoleRouting = {
    phases: [
      { phase: "diagnose", nodes: [node("a", [1]), node("b", [1])] },
      { phase: "build", nodes: [node("c", [2])] },
    ],
  };

  test("flatten lists the steps in the order of the page", () => {
    expect(RoutingDraft.flatten(routing).map((n) => n.key)).toEqual(["a", "b", "c"]);
  });

  test("replace puts saved steps into their places and leaves the others", () => {
    const saved = { ...node("b", [1, 2]), timeout_s: 5 };

    const next = RoutingDraft.replace(routing, [saved, node("unknown", [1])]);

    expect(next.phases.map((p) => p.nodes.map((n) => n.key))).toEqual([["a", "b"], ["c"]]);
    expect(next.phases[0].nodes[1]).toBe(saved);
    expect(next.phases[0].nodes[0]).toBe(routing.phases[0].nodes[0]);
    expect(routing.phases[0].nodes[1].timeout_s).toBe(120);
  });
});
