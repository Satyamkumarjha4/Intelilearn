/**
 * Unit under test: `lib/console-audit.ts`, which turns the change log's raw entries into sentences, areas and diffs.
 *
 * Why: the log is how a maintainer answers "who changed that, and what was it before?". An entry that says only
 * "model.update" or shows a model by its row number, a diff that prints `[object Object]`, or a filter that hides a
 * change under the wrong area would make the log useless exactly when something has gone wrong.
 *
 * Use cases:
 * - each kind of change reads as a sentence with the things it touched marked as code: models (added, changed,
 *   turned on or off, deleted, tested), providers, routing steps (settings, models added, removed or reordered),
 *   lesson settings, and runs (retried, stopped); a model tested with no name in the entry is looked up by its id
 * - field names read as words ("timeout_s" is "timeout"), the ones that are jargon get a plain name
 * - a list of fields reads naturally ("a", "a and b", "a, b and c", "a, b, c and 2 more")
 * - an unknown action still gives a sentence that names the action and its target
 * - the actor shows an initial and a name, falling back to the stored email and to "Someone"
 * - areas: routing (steps), models (models and providers), settings (lesson settings), runs; unknown targets are in none
 * - filtering by area keeps the order and keeps everything for "all"; the address holds only a known area
 * - the diff lists each changed field with before and after in words: on/off, dashes for nothing, the model chain as
 *   "a → b", nested values as compact JSON; a created or deleted thing has one empty side
 */
import { describe, expect, test } from "bun:test";

import { AuditAreas, type AuditArea, AuditDiff, AuditText } from "./console-audit";
import type { AuditEntry } from "./types";

function entry(patch: Partial<AuditEntry>): AuditEntry {
  return {
    id: 1,
    actor: { id: "u1", name: "Satyam", email: "satyam@example.com" },
    actor_email: "satyam@example.com",
    action: "model.update",
    target_type: "model",
    target_id: "12",
    before: null,
    after: null,
    changed_fields: [],
    created_at: "2026-03-15T10:00:00Z",
    ...patch,
  };
}

const plain = (segments: { text: string; code?: boolean }[]) => segments.map((s) => (s.code ? `<${s.text}>` : s.text)).join("");

describe("AuditText.sentence: models and providers", () => {
  test("a changed model names its fields and the model", () => {
    const e = entry({ before: { name: "gpt-oss-120b", rpm_limit: 30 }, after: { name: "gpt-oss-120b", rpm_limit: 60 }, changed_fields: ["rpm_limit"] });

    expect(plain(AuditText.sentence(e))).toBe("Changed rate limit of model <gpt-oss-120b>");
  });

  test("switching a model or provider on or off says so", () => {
    const off = entry({ before: { name: "m", enabled: true }, after: { name: "m", enabled: false }, changed_fields: ["enabled"] });
    const on = entry({ action: "provider.update", target_type: "provider", target_id: "groq", before: { enabled: false }, after: { enabled: true }, changed_fields: ["enabled"] });

    expect(plain(AuditText.sentence(off))).toBe("Turned model <m> off");
    expect(plain(AuditText.sentence(on))).toBe("Turned provider <groq> on");
  });

  test("a changed provider is named by its key", () => {
    const e = entry({ action: "provider.update", target_type: "provider", target_id: "groq", changed_fields: ["base_url", "rpm_limit"] });

    expect(plain(AuditText.sentence(e))).toBe("Changed base URL and rate limit of provider <groq>");
  });

  test("a model is added and deleted by name", () => {
    expect(plain(AuditText.sentence(entry({ action: "model.create", after: { name: "new-model" } })))).toBe("Added model <new-model>");
    expect(plain(AuditText.sentence(entry({ action: "model.delete", before: { name: "old-model" } })))).toBe("Deleted model <old-model>");
  });

  test("a test says how it went, and finds the model's name by its id when the entry has none", () => {
    const worked = entry({ action: "model.probe", after: { ok: true } });
    const failed = entry({ action: "model.probe", after: { ok: false } });
    const names = new Map([["12", "gpt-oss-120b"]]);

    expect(plain(AuditText.sentence(worked, names))).toBe("Tested model <gpt-oss-120b>: it worked");
    expect(plain(AuditText.sentence(failed, names))).toBe("Tested model <gpt-oss-120b>: it failed");
    expect(plain(AuditText.sentence(worked))).toBe("Tested model <12>: it worked");
  });
});

describe("AuditText.sentence: routing, settings and runs", () => {
  const chain = (...labels: string[]) => labels.map((model_label) => ({ model_label, enabled: true }));

  test("a step with its settings changed", () => {
    const e = entry({ action: "node.update", target_type: "node", target_id: "lesson.plan", before: { timeout_s: 60, bindings: chain("a") }, after: { timeout_s: 90, bindings: chain("a") }, changed_fields: ["timeout_s"] });

    expect(plain(AuditText.sentence(e))).toBe("Changed timeout of <lesson.plan>");
  });

  test("models added to, removed from and reordered in a step's chain", () => {
    const base = { action: "node.update", target_type: "node", target_id: "lesson.plan", changed_fields: ["bindings"] };
    const added = entry({ ...base, before: { bindings: chain("a") }, after: { bindings: chain("a", "b") } });
    const removed = entry({ ...base, before: { bindings: chain("a", "b") }, after: { bindings: chain("a") } });
    const moved = entry({ ...base, before: { bindings: chain("a", "b") }, after: { bindings: chain("b", "a") } });

    expect(plain(AuditText.sentence(added))).toBe("Added <b> to <lesson.plan>");
    expect(plain(AuditText.sentence(removed))).toBe("Removed <b> from <lesson.plan>");
    expect(plain(AuditText.sentence(moved))).toBe("Changed the order of the models of <lesson.plan>");
  });

  test("settings and chain changes together make two sentences", () => {
    const e = entry({ action: "node.update", target_type: "node", target_id: "x", before: { enabled: true, bindings: chain("a") }, after: { enabled: true, max_attempts: 3, bindings: chain("a", "b") }, changed_fields: ["bindings", "max_attempts"] });

    expect(plain(AuditText.sentence(e))).toBe("Changed max attempts of <x>. Added <b> to <x>");
  });

  test("lesson settings list what changed", () => {
    const e = entry({ action: "flow_settings.update", target_type: "flow_settings", target_id: "1", changed_fields: ["final_test_max", "alignment_min_score"] });

    expect(plain(AuditText.sentence(e))).toBe("Changed lesson settings: final test max and alignment min score");
  });

  test("runs are retried or stopped, named by the start of their id", () => {
    const id = "7f3a1b2c-1111-2222-3333-444455556666";

    expect(plain(AuditText.sentence(entry({ action: "run.retry", target_type: "run", target_id: id })))).toBe("Retried run <7f3a1b2c>");
    expect(plain(AuditText.sentence(entry({ action: "run.cancel", target_type: "run", target_id: id })))).toBe("Stopped run <7f3a1b2c>");
  });

  test("an unknown action still says what it was and what it was done to", () => {
    expect(plain(AuditText.sentence(entry({ action: "thing.frobnicate", target_type: "thing", target_id: "9" })))).toBe("Ran <thing.frobnicate> on <9>");
  });
});

describe("AuditText.list", () => {
  test.each([
    [[], ""],
    [["a"], "a"],
    [["a", "b"], "a and b"],
    [["a", "b", "c"], "a, b and c"],
    [["a", "b", "c", "d", "e"], "a, b, c and 2 more"],
  ])("%p reads %p", (items, text) => {
    expect(AuditText.list(items)).toBe(text);
  });
});

describe("AuditText.fieldName", () => {
  test.each([
    ["rpm_limit", "rate limit"],
    ["timeout_s", "timeout"],
    ["base_url", "base URL"],
    ["bindings", "models"],
    ["params_override", "parameters"],
    ["max_attempts", "max attempts"],
  ])("%s reads %s", (field, text) => {
    expect(AuditText.fieldName(field)).toBe(text);
  });
});

describe("AuditText.actor", () => {
  test("uses the account's name, then the stored email, then someone", () => {
    expect(AuditText.actor(entry({}))).toEqual({ initial: "S", name: "Satyam", title: "satyam@example.com" });
    expect(AuditText.actor(entry({ actor: null }))).toEqual({ initial: "S", name: "satyam@example.com", title: "satyam@example.com" });
    expect(AuditText.actor(entry({ actor: null, actor_email: "" }))).toEqual({ initial: "?", name: "Someone", title: "" });
  });
});

describe("AuditAreas", () => {
  test.each<[string, AuditArea | null]>([
    ["node", "routing"],
    ["model", "models"],
    ["provider", "models"],
    ["flow_settings", "settings"],
    ["run", "runs"],
    ["mystery", null],
  ])("a %s change is in %p", (target, area) => {
    expect(AuditAreas.of(entry({ target_type: target }))).toBe(area);
  });

  test("filtering keeps the order, and all keeps everything", () => {
    const rows = [entry({ id: 3, target_type: "run" }), entry({ id: 2, target_type: "node" }), entry({ id: 1, target_type: "run" })];

    expect(AuditAreas.filter(rows, "runs").map((r) => r.id)).toEqual([3, 1]);
    expect(AuditAreas.filter(rows, "").map((r) => r.id)).toEqual([3, 2, 1]);
  });

  test("the address holds only a known area", () => {
    expect(AuditAreas.parse("routing")).toBe("routing");
    expect(AuditAreas.parse("nonsense")).toBe("");
    expect(AuditAreas.parse(null)).toBe("");
    expect(AuditAreas.query("models")).toBe("?area=models");
    expect(AuditAreas.query("")).toBe("");
    expect(AuditAreas.OPTIONS.map((o) => o.value)).toEqual(["routing", "models", "settings", "runs"]);
  });
});

describe("AuditDiff", () => {
  test("lists each changed field with before and after in words", () => {
    const e = entry({ before: { enabled: true, rpm_limit: null, base_url: "" }, after: { enabled: false, rpm_limit: 30, base_url: "" }, changed_fields: ["enabled", "rpm_limit"] });

    expect(AuditDiff.rows(e)).toEqual([
      { field: "enabled", before: "on", after: "off" },
      { field: "rate limit", before: "–", after: "30" },
    ]);
  });

  test("a model chain reads as names in order, and nested values as compact JSON", () => {
    const e = entry({
      before: { bindings: [{ model_label: "a" }, { model_label: "b" }], params_override: {} },
      after: { bindings: [], params_override: { temperature: 0.2 } },
      changed_fields: ["bindings", "params_override"],
    });

    expect(AuditDiff.rows(e)).toEqual([
      { field: "models", before: "a → b", after: "none" },
      { field: "parameters", before: "{}", after: '{"temperature":0.2}' },
    ]);
  });

  test("a created or deleted thing has an empty side, and an entry with nothing to compare has no rows", () => {
    const created = entry({ action: "model.create", before: null, after: { name: "m" }, changed_fields: ["name"] });
    const deleted = entry({ action: "model.delete", before: { name: "m" }, after: null, changed_fields: ["name"] });

    expect(AuditDiff.rows(created)).toEqual([{ field: "name", before: "–", after: "m" }]);
    expect(AuditDiff.rows(deleted)).toEqual([{ field: "name", before: "m", after: "–" }]);
    expect(AuditDiff.rows(entry({ before: null, after: null, changed_fields: [] }))).toEqual([]);
  });

  test("a field the snapshots lack on one side is a dash", () => {
    expect(AuditDiff.rows(entry({ before: {}, after: { ok: true }, changed_fields: ["ok"] }))).toEqual([{ field: "ok", before: "–", after: "on" }]);
  });
});
