/**
 * Unit under test: `SpecSelector`, which decides from the files a change touched which e2e specs have to run, using the
 * checked-in map `e2e/spec-map.json` (the format is read by `make e2e-affected`).
 *
 * Why: a full e2e run is ten minutes, so it cannot run on every change; but a map that is too narrow lets a break reach
 * `main` unseen. The rules here are what make narrowing safe: anything that cannot be narrowed (shared auth, the shell,
 * the API client, the stack itself) runs everything, and a file nobody mapped runs everything rather than nothing.
 *
 * Use cases:
 * - a changed file that matches a trigger runs every spec, and says which file and why
 * - a file in `no_spec` needs no browser run, and a change of only such files runs nothing
 * - a mapped file runs the specs of its entry; the specs of several files are added together, in the order of the specs
 * - a group name (`@build`) stands for the specs in it
 * - a file in no entry at all runs every spec, and is named as unmapped
 * - a trigger wins over a map entry that also matches the file
 * - the `manual` specs (those that need a live provider) are never selected, not even by a full run
 * - a glob handles `**`, `*` and `{a,b}`, and a dotted folder
 */
import { describe, expect, test } from "bun:test";

import { SpecSelector, type SpecMap } from "./spec-selector";

const SPECS = ["a.spec.ts", "b.spec.ts", "c.spec.ts", "d.spec.ts", "live.spec.ts"];

const MAP: SpecMap = {
  groups: { pair: ["b.spec.ts", "c.spec.ts"] },
  manual: ["live.spec.ts"],
  triggers: [{ globs: ["frontend/proxy.ts", "backend/core/**", "backend/*/migrations/**"], why: "shared by every request" }],
  map: [
    { globs: ["frontend/app/lessons/**", "backend/lessons/**"], specs: ["@pair"] },
    { globs: ["frontend/lib/{wallet,streak}.ts"], specs: ["d.spec.ts"] },
    { globs: ["backend/lessons/views.py"], specs: ["a.spec.ts"] },
    { globs: [".github/**"], specs: ["a.spec.ts"] },
  ],
  no_spec: [{ globs: ["docs/**", "**/*.md", "tests/**/*.py"], why: "documents and unit tests" }],
};

const select = (files: string[]) => new SpecSelector(MAP, SPECS).select(files);

describe("SpecSelector", () => {
  test("a trigger runs every spec and names the file and the reason", () => {
    const selection = select(["backend/core/errors.py", "frontend/app/lessons/page.tsx"]);

    expect(selection.full).toBe(true);
    expect(selection.fullBecause).toContain("backend/core/errors.py");
    expect(selection.fullBecause).toContain("shared by every request");
    expect(selection.specs).toEqual(["a.spec.ts", "b.spec.ts", "c.spec.ts", "d.spec.ts"]);
  });

  test("files that need no spec run nothing", () => {
    const selection = select(["docs/process/testing.md", "tests/credits/test_ledger.py", "README.md"]);

    expect(selection.full).toBe(false);
    expect(selection.specs).toEqual([]);
    expect(selection.verdicts.map((v) => v.kind)).toEqual(["no_spec", "no_spec", "no_spec"]);
  });

  test("a mapped file runs its specs, and several files add theirs, in the order of the specs", () => {
    const selection = select(["frontend/lib/streak.ts", "frontend/app/lessons/page.tsx"]);

    expect(selection.full).toBe(false);
    expect(selection.specs).toEqual(["b.spec.ts", "c.spec.ts", "d.spec.ts"]);
  });

  test("a file may match several entries: their specs are added together", () => {
    expect(select(["backend/lessons/views.py"]).specs).toEqual(["a.spec.ts", "b.spec.ts", "c.spec.ts"]);
  });

  test("a group name stands for the specs in it", () => {
    const verdict = select(["frontend/app/lessons/page.tsx"]).verdicts[0]!;

    expect(verdict.kind).toBe("map");
    expect(verdict.specs).toEqual(["b.spec.ts", "c.spec.ts"]);
  });

  test("a file in no entry runs every spec, and is named as unmapped", () => {
    const selection = select(["frontend/app/brand-new-area/page.tsx"]);

    expect(selection.full).toBe(true);
    expect(selection.fullBecause).toContain("frontend/app/brand-new-area/page.tsx");
    expect(selection.fullBecause).toContain("spec-map.json");
    expect(selection.verdicts[0]!.kind).toBe("unmapped");
  });

  test("a trigger wins over a map entry that matches the same file", () => {
    const withBoth: SpecMap = { ...MAP, map: [{ globs: ["backend/core/**"], specs: ["a.spec.ts"] }] };

    const selection = new SpecSelector(withBoth, SPECS).select(["backend/core/x.py"]);

    expect(selection.full).toBe(true);
    expect(selection.verdicts[0]!.kind).toBe("trigger");
  });

  test("a migration of any app is a trigger, the app's other files are not", () => {
    expect(select(["backend/lessons/migrations/0030_x.py"]).full).toBe(true);
    expect(select(["backend/lessons/views.py"]).full).toBe(false);
  });

  test("the manual specs are never selected", () => {
    const withManual: SpecMap = { ...MAP, map: [{ globs: ["x/**"], specs: ["live.spec.ts", "a.spec.ts"] }] };

    expect(new SpecSelector(withManual, SPECS).select(["x/y.ts"]).specs).toEqual(["a.spec.ts"]);
    expect(select(["backend/core/errors.py"]).specs).not.toContain("live.spec.ts");
  });

  test("nothing changed runs nothing", () => {
    const selection = select([]);

    expect(selection.full).toBe(false);
    expect(selection.specs).toEqual([]);
  });

  test("a dotted folder matches its glob", () => {
    expect(select([".github/workflows/ci.yml"]).specs).toEqual(["a.spec.ts"]);
  });

  test("a spec named in the map that does not exist is reported, not silently ignored", () => {
    const broken: SpecMap = { ...MAP, map: [{ globs: ["x/**"], specs: ["gone.spec.ts"] }] };

    expect(() => new SpecSelector(broken, SPECS).select(["x/y.ts"])).toThrow("gone.spec.ts");
  });

  test("an unknown group is reported, not silently ignored", () => {
    const broken: SpecMap = { ...MAP, map: [{ globs: ["x/**"], specs: ["@nobody"] }] };

    expect(() => new SpecSelector(broken, SPECS).select(["x/y.ts"])).toThrow("@nobody");
  });
});
