/**
 * Unit under test: `RoutingProfile`, which turns a profile preview into a list for the staff to review and then
 * loads it into the local routing edits.
 *
 * Why: a profile rewrites the chains of many steps at once. The preview endpoint saves nothing, and the page must keep
 * it that way: applying only fills the local edits, which the staff reviews and saves (or discards) as any other
 * edit. A merge that overwrites a step the profile does not change would throw away someone's unsaved work, and one
 * that loads a step the registry cannot serve (a model it lacks) would offer a Save that the API refuses.
 *
 * Use cases:
 * - lists each step the profile would change, with its chain and effort before and after
 * - leaves out steps the profile does not change
 * - marks a step the profile cannot apply (a problem, or a model the registry lacks) and says why
 * - merging puts the proposed settings and chain into the edits of the changed steps that can be applied
 * - merging keeps the edits of every other step, and skips the blocked ones
 * - the summary says how many steps change and how many cannot
 */
import { describe, expect, test } from "bun:test";

import { RoutingDraft } from "./routing-draft";
import { RoutingProfile } from "./routing-profile";
import type { NodeRouting, ProfilePreview, RoutingBinding } from "./types";

const binding = (model: number | null, label: string): RoutingBinding => ({
  model,
  model_label: label,
  enabled: true,
  max_retries: 2,
  overrides: { params: {}, reasoning_effort: "" },
  problems: [],
});

const node = (key: string, chain: [number | null, string][], extra: Partial<NodeRouting> = {}): NodeRouting => ({
  key,
  phase: "author",
  description: `${key} does a thing`,
  optional: false,
  output: "structured",
  requires: [],
  min_output_tokens: 0,
  min_context: 0,
  enabled: true,
  reasoning_effort: "high",
  max_attempts: 3,
  max_tool_steps: null,
  timeout_s: 120,
  params_override: {},
  bindings: chain.map(([id, label]) => binding(id, label)),
  ...extra,
});

const entry = (current: NodeRouting, proposed: NodeRouting, problems: string[] = []) => ({
  key: current.key,
  changed: JSON.stringify(RoutingDraft.input(current)) !== JSON.stringify(RoutingDraft.input(proposed)),
  current,
  proposed,
  problems,
});

const big = node("a", [[1, "groq/big"], [2, "google/mid"]]);
const small = node("a", [[3, "groq/small"]], { reasoning_effort: "low" });
const same = node("b", [[1, "groq/big"]]);
const lacks = node("c", [[null, "openai/gpt-x"]]);
const preview: ProfilePreview = {
  profile: "cheap",
  label: "Cheap: Groq first",
  nodes: [entry(big, small), entry(same, same), entry(node("c", [[1, "groq/big"]]), lacks, ["Model openai/gpt-x does not exist."])],
  summary: { total: 3, changed: 2, blocked: 1 },
};

describe("changes", () => {
  test("lists the steps that change, with chain and effort before and after", () => {
    const [change] = RoutingProfile.changes(preview).filter((c) => c.key === "a");

    expect(change).toMatchObject({
      key: "a",
      blocked: false,
      chain: { before: ["groq/big", "google/mid"], after: ["groq/small"] },
      effort: { before: "high", after: "low" },
      problems: [],
    });
  });

  test("leaves out the steps that do not change", () => {
    expect(RoutingProfile.changes(preview).map((c) => c.key)).toEqual(["a", "c"]);
  });

  test("an unchanged effort is not listed as a change", () => {
    const chainOnly = entry(big, node("a", [[3, "groq/small"]]));

    expect(RoutingProfile.changes({ ...preview, nodes: [chainOnly] })[0].effort).toBeNull();
  });

  test("a step with a problem, or a model the registry lacks, is blocked and says why", () => {
    const blocked = RoutingProfile.changes(preview).find((c) => c.key === "c");

    expect(blocked).toMatchObject({ blocked: true, problems: ["Model openai/gpt-x does not exist."] });
    const lacksOnly = entry(node("d", [[1, "groq/big"]]), lacks);
    expect(RoutingProfile.changes({ ...preview, nodes: [lacksOnly] })[0]).toMatchObject({ blocked: true });
    expect(RoutingProfile.changes({ ...preview, nodes: [lacksOnly] })[0].problems[0]).toContain("openai/gpt-x");
  });
});

describe("merge", () => {
  const edits = [big, same, node("c", [[1, "groq/big"]]), node("z", [[1, "groq/big"]])];

  test("loads the proposed settings and chain into the steps that change", () => {
    const { drafts, applied } = RoutingProfile.merge(edits, preview);

    const a = drafts.find((n) => n.key === "a")!;
    expect(a.bindings.map((b) => b.model_label)).toEqual(["groq/small"]);
    expect(a.reasoning_effort).toBe("low");
    expect(a.description).toBe("a does a thing");
    expect(applied).toEqual(["a"]);
  });

  test("keeps the edits of steps the profile does not touch, and skips the blocked ones", () => {
    const edited = edits.map((n) => (n.key === "b" ? { ...n, timeout_s: 30 } : n));
    const { drafts, skipped } = RoutingProfile.merge(edited, preview);

    expect(drafts.find((n) => n.key === "b")!.timeout_s).toBe(30);
    expect(drafts.find((n) => n.key === "c")!.bindings[0].model).toBe(1);
    expect(drafts.find((n) => n.key === "z")).toBe(edits[3]);
    expect(skipped).toEqual(["c"]);
  });

  test("a step the profile names but the page does not have is ignored", () => {
    const { drafts } = RoutingProfile.merge([big], { ...preview, nodes: [entry(node("q", [[1, "x/y"]]), node("q", [[2, "x/z"]]))] });

    expect(drafts).toEqual([big]);
  });

  test("does not change the edits it was given", () => {
    RoutingProfile.merge(edits, preview);

    expect(edits[0].bindings).toHaveLength(2);
  });
});

describe("summary", () => {
  test("says how many steps change and how many cannot be applied", () => {
    const [a, c] = RoutingProfile.changes(preview);

    expect(RoutingProfile.summary([a, c])).toBe("2 steps change · 1 cannot be applied");
    expect(RoutingProfile.summary([a])).toBe("1 step changes");
    expect(RoutingProfile.summary([])).toBe("Nothing would change");
  });
});
