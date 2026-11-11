/**
 * `make e2e-affected`: runs only the e2e specs a change can touch, and says which and why.
 *
 *   make e2e-affected                  against main
 *   make e2e-affected BASE=some-branch against another ref
 *   make e2e-affected PLAN=1           print the plan, run nothing
 *
 * The changed files are everything that differs from the merge-base of BASE and HEAD (commits, staged and unstaged changes)
 * plus untracked files. A change to a trigger, or to a file that is in no entry of spec-map.json, runs every spec; if the
 * base cannot be found, so does that. It leaves the stack running (and reuses it next time) unless a trigger changed.
 * Rules and the map: e2e/spec-map.json, docs/process/test-audit.md, docs/process/testing.md.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { E2ERun } from "./run";
import { SpecSelector, type SpecMap } from "./spec-selector";
import { AffectedReport, ChangedFiles } from "./support/affected-report";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const git = (...args: string[]) => execFileSync("git", args, { cwd: ROOT, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });

class Affected {
  private readonly specs = readdirSync(join(ROOT, "e2e/tests")).filter((name) => name.endsWith(".spec.ts")).sort();
  private readonly map: SpecMap = JSON.parse(readFileSync(join(ROOT, "e2e/spec-map.json"), "utf8"));

  constructor(private readonly base: string) {}

  /** The files changed against the base, or null when the base cannot be resolved. */
  changedFiles(): string[] | null {
    let mergeBase: string;
    try {
      mergeBase = git("merge-base", this.base, "HEAD").trim();
    } catch {
      return null;
    }
    return ChangedFiles.parse(git("diff", "--name-only", mergeBase), git("ls-files", "--others", "--exclude-standard"));
  }

  /** Whether the throwaway stack answers: the API and the frontend's sign-in page. */
  static stackAnswers(): boolean {
    const api = process.env.E2E_API_URL ?? "http://localhost:7110";
    const web = process.env.E2E_BASE_URL ?? "http://localhost:7100";
    const ok = (url: string) => spawnSync("curl", ["-sf", "-o", "/dev/null", "--max-time", "5", url]).status === 0;
    return ok(`${api}/api/health`) && ok(`${web}/auth`);
  }

  main(plan: boolean): number {
    const files = this.changedFiles();
    const selector = new SpecSelector(this.map, this.specs);
    const everything =
      files === null
        ? selector.all(`the base "${this.base}" cannot be found (git merge-base ${this.base} HEAD failed)`)
        : selector.select(files);
    if (files !== null) console.log(`e2e-affected against ${this.base}: ${files.length} changed file${files.length === 1 ? "" : "s"}\n`);
    for (const line of AffectedReport.of(everything, this.specs.length).lines()) console.log(line);
    if (plan || !everything.specs.length) return 0;

    // Reuse the stack the last run left. A trigger changed what runs in it (dependencies, settings, migrations, the stack's own files),
    // so that one is rebuilt; so is one that does not answer.
    const rebuild = files === null || everything.verdicts.some((v) => v.kind === "trigger");
    if (rebuild || !Affected.stackAnswers()) {
      console.log(rebuild ? "\nstarting the stack (a trigger changed, or no base)" : "\nstarting the stack (it does not answer)");
      const up = spawnSync("make", ["-C", ROOT, "fake-llm"], { stdio: "inherit" });
      if (up.status !== 0) return up.status ?? 1;
    } else {
      console.log("\nreusing the running stack");
    }
    return E2ERun.run(everything.specs);
  }
}

if (import.meta.main) {
  const args = process.argv.slice(2);
  process.exit(new Affected(process.env.BASE || "main").main(args.includes("--plan")));
}
