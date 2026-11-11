/**
 * Unit under test: `AffectedReport`, which prints what `make e2e-affected` decided and why, and `ChangedFiles.parse`, which
 * reads git's output into the list of files a change touched.
 *
 * Why: the point of choosing specs is trust. A person (or an agent) reading the output must be able to see which specs ran for
 * which file, and why a run was widened to everything, or the narrowing cannot be believed. The same lines go in the report
 * of every piece of work ("which e2e specs ran and why").
 *
 * Use cases:
 * - each file that brings specs is listed with them; the files that need none are one line, with the reason once
 * - a full run says so in one line, with the file and the reason
 * - the closing line says how many of the specs run, and names them
 * - a change that needs no spec says so and runs nothing
 * - git's file lists are parsed: blank lines dropped, duplicates (a file both changed and untracked) once, in order
 */
import { describe, expect, test } from "bun:test";

import { AffectedReport, ChangedFiles } from "./support/affected-report";
import { SpecSelector, type SpecMap } from "./spec-selector";

const SPECS = ["credits.spec.ts", "journey.spec.ts", "landing.spec.ts", "quizzes.spec.ts"];
const MAP: SpecMap = {
  groups: {},
  manual: [],
  triggers: [{ globs: ["backend/core/**"], why: "settings, URLs, auth, errors" }],
  map: [{ globs: ["backend/credits/**"], specs: ["credits.spec.ts", "journey.spec.ts"] }],
  no_spec: [{ globs: ["docs/**"], why: "documents" }],
};
const report = (files: string[]) => AffectedReport.of(new SpecSelector(MAP, SPECS).select(files), SPECS.length).lines();

describe("AffectedReport", () => {
  test("each changed file is listed with its reason and the specs it brings", () => {
    const lines = report(["backend/credits/ledger.py", "docs/process/testing.md"]);

    expect(lines.some((line) => line.includes("backend/credits/ledger.py") && line.includes("credits, journey"))).toBe(true);
    expect(lines).toContain("no spec needed (1 file, documents): docs/process/testing.md");
  });

  test("the closing line says how many specs run and names them", () => {
    const last = report(["backend/credits/ledger.py"]).at(-1)!;

    expect(last).toBe("running 2 of 4 specs: credits, journey");
  });

  test("a trigger widens the run to every spec, and says which file and why", () => {
    const lines = report(["backend/core/errors.py", "backend/credits/ledger.py"]);

    expect(lines.join("\n")).toContain("FULL RUN because backend/core/errors.py matches a trigger (settings, URLs, auth, errors)");
    expect(lines.at(-1)).toBe("running 4 of 4 specs: credits, journey, landing, quizzes");
  });

  test("an unmapped file widens the run and tells how to map it", () => {
    const lines = report(["frontend/app/new-area/page.tsx"]);

    expect(lines.join("\n")).toContain("FULL RUN because frontend/app/new-area/page.tsx is in no entry");
    expect(lines.join("\n")).toContain("e2e/spec-map.json");
  });

  test("a change that needs no spec runs nothing and says so", () => {
    const lines = report(["docs/process/testing.md"]);

    expect(lines.at(-1)).toBe("running 0 of 4 specs: nothing to run (every changed file needs no browser spec)");
  });

  test("no changed file at all is nothing to run", () => {
    expect(report([]).at(-1)).toBe("running 0 of 4 specs: nothing to run (no file changed against the base)");
  });
});

describe("trigger files", () => {
  test("are one line per reason however many there are, naming the first few", () => {
    const files = Array.from({ length: 8 }, (_, n) => `backend/core/file-${n}.py`);

    const lines = report([...files, "backend/credits/ledger.py"]);
    const line = lines.find((l) => l.startsWith("runs everything"))!;

    expect(lines.filter((l) => l.startsWith("runs everything"))).toHaveLength(1);
    expect(line).toContain("(8 files, settings, URLs, auth, errors)");
    expect(line).toContain("backend/core/file-0.py");
    expect(line).toContain("and 3 more");
    expect(line).not.toContain("file-7");
  });
});

describe("the files that need no spec", () => {
  test("are one line however many there are, naming the first few", () => {
    const files = Array.from({ length: 9 }, (_, n) => `docs/page-${n}.md`);

    const line = report(files).find((l) => l.startsWith("no spec needed"))!;

    expect(line).toContain("(9 files, documents)");
    expect(line).toContain("docs/page-0.md");
    expect(line).toContain("and 4 more");
    expect(line).not.toContain("docs/page-8.md");
  });
});

describe("ChangedFiles.parse", () => {
  test("blank lines are dropped and a file listed twice is kept once, in order", () => {
    const changed = "backend/a.py\nfrontend/b.ts\n\n";
    const untracked = "frontend/b.ts\ne2e/new.ts\n";

    expect(ChangedFiles.parse(changed, untracked)).toEqual(["backend/a.py", "frontend/b.ts", "e2e/new.ts"]);
  });
});
