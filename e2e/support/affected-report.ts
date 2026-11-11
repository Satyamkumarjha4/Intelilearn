import type { Selection } from "../spec-selector";

const short = (spec: string) => spec.replace(/\.spec\.ts$/, "");

/** What `make e2e-affected` prints: each changed file, why it was classified as it was, and the specs that will run. */
export class AffectedReport {
  private constructor(
    private readonly selection: Selection,
    private readonly total: number,
  ) {}

  static of(selection: Selection, total: number): AffectedReport {
    return new AffectedReport(selection, total);
  }

  lines(): string[] {
    const { selection, total } = this;
    const out: string[] = [];
    if (selection.verdicts.length) {
      const width = Math.min(60, Math.max(...selection.verdicts.map((v) => v.file.length)));
      for (const verdict of selection.verdicts) {
        const what =
          verdict.kind === "map"
            ? verdict.specs.map(short).join(", ") || "(manual specs only: none run)"
            : verdict.kind === "no_spec"
              ? `no spec needed: ${verdict.why}`
              : verdict.kind === "trigger"
                ? `runs everything: ${verdict.why}`
                : "runs everything: not in spec-map.json";
        out.push(`${verdict.file.padEnd(width)}  ${what}`);
      }
    }
    if (selection.full) out.push(`FULL RUN because ${selection.fullBecause}`);
    const names = selection.specs.map(short).join(", ");
    const none = selection.verdicts.length ? "every changed file needs no browser spec" : "no file changed against the base";
    out.push(`running ${selection.specs.length} of ${total} specs: ${names || `nothing to run (${none})`}`);
    return out;
  }
}

/** The files a change touched, from `git diff --name-only <merge-base>` and `git ls-files --others --exclude-standard`. */
export class ChangedFiles {
  static parse(...lists: string[]): string[] {
    const seen = new Set<string>();
    for (const list of lists) for (const line of list.split("\n")) if (line.trim()) seen.add(line.trim());
    return [...seen];
  }
}
