/** Chooses which e2e specs to run for a set of changed files, from the checked-in map `e2e/spec-map.json`. */

export type SpecMap = {
  /** Names for sets of specs: `"build": ["journey.spec.ts", …]` is written `@build` in an entry. */
  groups: Record<string, string[]>;
  /** Specs that are never run automatically (they need a live payment provider). */
  manual: string[];
  /** A change here runs every spec: it cannot be narrowed. */
  triggers: { globs: string[]; why: string }[];
  /** A change here runs these specs (the specs of every matching entry are added together). */
  map: { globs: string[]; specs: string[] }[];
  /** A change here needs no browser run. */
  no_spec: { globs: string[]; why: string }[];
};

export type Verdict = { file: string; kind: "trigger" | "no_spec" | "map" | "unmapped"; why: string; specs: string[] };

export type Selection = {
  /** True when every spec runs (a trigger, or a file nobody mapped). */
  full: boolean;
  /** The sentence that says why, when `full`. */
  fullBecause: string | null;
  verdicts: Verdict[];
  /** The specs to run, in the order of the spec files. */
  specs: string[];
};

export class SpecSelector {
  private readonly manual: Set<string>;

  /** `allSpecs` are the file names of the specs that exist (`tests/*.spec.ts`), in the order they run. */
  constructor(
    private readonly map: SpecMap,
    private readonly allSpecs: readonly string[],
  ) {
    this.manual = new Set(map.manual);
  }

  private static readonly compiled = new Map<string, InstanceType<typeof Bun.Glob>>();

  /** Whether `file` (a path from the repository root) matches any of `globs`. */
  static matches(globs: readonly string[], file: string): boolean {
    return globs.some((glob) => {
      let compiled = SpecSelector.compiled.get(glob);
      if (!compiled) SpecSelector.compiled.set(glob, (compiled = new Bun.Glob(glob)));
      return compiled.match(file);
    });
  }

  verdict(file: string): Verdict {
    const trigger = this.map.triggers.find((entry) => SpecSelector.matches(entry.globs, file));
    if (trigger) return { file, kind: "trigger", why: trigger.why, specs: [] };

    const none = this.map.no_spec.find((entry) => SpecSelector.matches(entry.globs, file));
    if (none) return { file, kind: "no_spec", why: none.why, specs: [] };

    const entries = this.map.map.filter((entry) => SpecSelector.matches(entry.globs, file));
    if (entries.length) {
      const specs = this.inOrder(entries.flatMap((entry) => this.expand(entry.specs)));
      return { file, kind: "map", why: "mapped", specs };
    }
    return { file, kind: "unmapped", why: "in no entry of e2e/spec-map.json", specs: [] };
  }

  select(files: readonly string[]): Selection {
    const verdicts = files.map((file) => this.verdict(file));
    const because = verdicts.find((v) => v.kind === "trigger" || v.kind === "unmapped");
    if (because) {
      const reason =
        because.kind === "trigger"
          ? `${because.file} matches a trigger (${because.why})`
          : `${because.file} is in no entry: add it to e2e/spec-map.json (a map entry, or no_spec with a reason)`;
      return { full: true, fullBecause: reason, verdicts, specs: this.inOrder(this.allSpecs) };
    }
    return { full: false, fullBecause: null, verdicts, specs: this.inOrder(verdicts.flatMap((v) => v.specs)) };
  }

  /** Every runnable spec, for a run that cannot be narrowed (for instance when the base ref cannot be found). */
  all(because: string): Selection {
    return { full: true, fullBecause: because, verdicts: [], specs: this.inOrder(this.allSpecs) };
  }

  /** Replaces each `@group` by its specs, and refuses a name that is not a group or a spec. */
  expand(names: readonly string[]): string[] {
    return names.flatMap((name) => {
      if (name.startsWith("@")) {
        const group = this.map.groups[name.slice(1)];
        if (!group) throw new Error(`e2e/spec-map.json names the group ${name}, which is not in "groups"`);
        return this.expand(group);
      }
      if (!this.allSpecs.includes(name)) throw new Error(`e2e/spec-map.json names ${name}, which is not a spec in e2e/tests`);
      return [name];
    });
  }

  /** The distinct, runnable specs of `names`, in the order the spec files run. */
  private inOrder(names: readonly string[]): string[] {
    const wanted = new Set(names);
    return this.allSpecs.filter((spec) => wanted.has(spec) && !this.manual.has(spec));
  }
}
