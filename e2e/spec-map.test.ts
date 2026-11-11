/**
 * Unit under test: `e2e/spec-map.json`, the checked-in map from changed files to the e2e specs that cover them (read by
 * `make e2e-affected`), checked against the real repository.
 *
 * Why: selective e2e is only safe while the map is complete. A spec nobody mapped never runs on a change; an app folder
 * nobody mapped either runs every spec each time (slow, and people stop using `e2e-affected`) or, worse, is quietly
 * ignored. This guard fails the day a spec, a source file or a whole source folder is added without a decision, and the
 * day a glob stops matching anything (a renamed folder that left its entry behind).
 *
 * Use cases:
 * - every spec file is run by some map entry or listed as manual, and every spec a map entry names exists
 * - every trigger, map and no_spec entry says why (no_spec and triggers) or runs something (map)
 * - no glob is dead: each matches at least one file of the repository
 * - every tracked file is a trigger, needs no spec, or is mapped: none would run everything as "unmapped"
 * - a source folder (a backend app, a frontend route, component or lib folder, sandbox) that needs no spec is one of the few
 *   named below: adding a whole folder to no_spec is a decision made here, in review, with a reason
 * - every other source folder has a spec that runs for it, or is a trigger: no folder is mapped to nothing
 */
import { describe, expect, test } from "bun:test";
import { execSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { SpecSelector, type SpecMap } from "./spec-selector";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const MAP: SpecMap = JSON.parse(readFileSync(join(ROOT, "e2e/spec-map.json"), "utf8"));
const SPECS = readdirSync(join(ROOT, "e2e/tests")).filter((name) => name.endsWith(".spec.ts")).sort();
const FILES = execSync("git ls-files", { cwd: ROOT, maxBuffer: 64 * 1024 * 1024 })
  .toString()
  .split("\n")
  .filter((file) => file && existsSync(join(ROOT, file)));
const selector = new SpecSelector(MAP, SPECS);

/** The source folders that need no browser run at all, and why. A new entry is a decision, made here. */
const NO_SPEC_FOLDERS: Record<string, string> = {
  "frontend/app/privacy": "static legal page, covered by the legal-document unit tests",
  "frontend/app/terms": "static legal page, covered by the legal-document unit tests",
  "frontend/app/contact": "static contact page, covered by its unit tests",
  "frontend/components/legal": "the legal pages' components",
  "frontend/components/contact": "the contact page's components",
};

/** `backend/<app>`, `frontend/app/<route>`, `frontend/components/<group>`, `frontend/lib/<group>` and `sandbox`. */
function sourceFolders(): string[] {
  const under = (parent: string) =>
    existsSync(join(ROOT, parent))
      ? readdirSync(join(ROOT, parent))
          .filter((name) => statSync(join(ROOT, parent, name)).isDirectory() && !name.startsWith(".") && !["node_modules", "__pycache__", "migrations", "(shell)"].includes(name))
          .map((name) => `${parent}/${name}`)
      : [];
  return [...under("backend"), ...under("frontend/app"), ...under("frontend/components"), ...under("frontend/lib"), "sandbox"];
}

describe("e2e/spec-map.json", () => {
  test("every spec is run by some entry or is manual, and every spec an entry names exists", () => {
    const run = new Set([...MAP.map.flatMap((entry) => selector.expand(entry.specs)), ...MAP.manual]);
    for (const trigger of MAP.manual) expect(SPECS, `manual spec ${trigger}`).toContain(trigger);

    expect(SPECS.filter((spec) => !run.has(spec)), "specs no map entry runs (add them to e2e/spec-map.json)").toEqual([]);
  });

  test("every trigger and no_spec entry says why, and every map entry runs something", () => {
    for (const entry of [...MAP.triggers, ...MAP.no_spec]) expect(entry.why.trim().length, entry.globs.join(" ")).toBeGreaterThan(10);
    for (const entry of MAP.map) expect(entry.specs.length, entry.globs.join(" ")).toBeGreaterThan(0);
  });

  test("no glob is dead: each matches at least one file", () => {
    const entries = [...MAP.triggers, ...MAP.map, ...MAP.no_spec];
    const dead = entries.flatMap((entry) => entry.globs).filter((glob) => !FILES.some((file) => SpecSelector.matches([glob], file)));

    expect(dead, "globs that match no file (a renamed or removed folder?)").toEqual([]);
  });

  test("every file of the repository is a trigger, needs no spec, or is mapped", () => {
    const unmapped = FILES.filter((file) => selector.verdict(file).kind === "unmapped");

    expect(unmapped.slice(0, 25), `${unmapped.length} files in no entry: each would run every e2e spec`).toEqual([]);
  });

  test("a source folder that needs no spec is one of the few named in this test", () => {
    const needsNone = sourceFolders().filter((folder) => {
      const mine = FILES.filter((file) => file.startsWith(`${folder}/`));
      return mine.length > 0 && mine.every((file) => selector.verdict(file).kind === "no_spec");
    });

    expect(needsNone.sort()).toEqual(Object.keys(NO_SPEC_FOLDERS).sort());
  });

  test("every source folder has a spec that runs for it, or is a trigger, or is one of those that need none", () => {
    const bare = sourceFolders().filter((folder) => {
      if (folder in NO_SPEC_FOLDERS) return false;
      const mine = FILES.filter((file) => file.startsWith(`${folder}/`)).map((file) => selector.verdict(file));
      const runsSomething = mine.some((verdict) => verdict.kind === "trigger" || (verdict.kind === "map" && verdict.specs.length > 0));
      return mine.length > 0 && !runsSomething;
    });

    expect(bare, "source folders with files but no spec that runs for them").toEqual([]);
  });
});
