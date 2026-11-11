export type Phase = { project: "global" | "learner"; specs: string[]; workers: number; warmUp: boolean };

/**
 * The two Playwright projects the specs run in (`playwright.config.ts`), and the plan for a run.
 *
 * `global`: the specs that change what every learner sees, run alone on one worker, first. `learner`: every other spec, side by
 * side on several workers, each with a learner of its own. The specs that need a live payment provider are in `global` so they
 * can be run by name; nothing selects them otherwise.
 */
export class E2EPhases {
  /** Specs that change shared state: the price table, the credit settings, the testimonials the landing page shows. */
  static readonly SERIAL = ["console-credits.spec.ts", "console.spec.ts", "credits.spec.ts", "landing.spec.ts"];
  /** Skipped without a provider's test keys (`make e2e-payments`). */
  static readonly MANUAL = ["payments-razorpay.spec.ts", "payments-stripe.spec.ts"];

  static projectOf(spec: string): Phase["project"] {
    return E2EPhases.SERIAL.includes(spec) || E2EPhases.MANUAL.includes(spec) ? "global" : "learner";
  }

  /** The files of the `global` project, as the regular expression `playwright.config.ts` matches them with. */
  static globalPattern(): RegExp {
    return new RegExp(`(${[...E2EPhases.SERIAL, ...E2EPhases.MANUAL].map((spec) => spec.replaceAll(".", "\\.")).join("|")})$`);
  }

  /** `specs` undefined is every spec; the list is the files to run, by name. The warm-up runs once, in the first phase. */
  static plan(specs: readonly string[] | undefined, workers: number): Phase[] {
    const count = Number.isFinite(workers) && workers >= 1 ? Math.floor(workers) : 1;
    const phases: Phase[] = [];
    for (const [project, size] of [["global", 1], ["learner", count]] as const) {
      const mine = specs?.filter((spec) => E2EPhases.projectOf(spec) === project) ?? [];
      if (specs === undefined || mine.length) phases.push({ project, specs: mine, workers: size, warmUp: phases.length === 0 });
    }
    return phases;
  }

  /** The arguments for `playwright test`: the project, the workers, `--no-deps` when the warm-up has already run, the spec files. */
  static args(phase: Phase): string[] {
    return [
      `--project=${phase.project}`,
      `--workers=${phase.workers}`,
      ...(phase.warmUp ? [] : ["--no-deps"]),
      ...phase.specs.map((spec) => `tests/${spec}`),
    ];
  }
}
