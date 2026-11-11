/**
 * Runs the e2e specs in their two phases (support/phases.ts): the serial ones on one worker, then the rest side by side.
 *
 *   bun run.ts                         every spec          (make e2e)
 *   bun run.ts credits.spec.ts …       the named specs     (make e2e-affected)
 *
 * The number of workers for the second phase is E2E_WORKERS (make's E2E_WORKERS, default 4). The exit code is non-zero when
 * any phase failed; both phases always run, so one report shows every failure.
 */
import { spawnSync } from "node:child_process";

import { E2EPhases } from "./support/phases";

export class E2ERun {
  static workers(): number {
    return Number(process.env.E2E_WORKERS ?? 4);
  }

  /** Runs the phases for `specs` (undefined: all) and returns the exit code. */
  static run(specs: readonly string[] | undefined): number {
    let code = 0;
    for (const phase of E2EPhases.plan(specs, E2ERun.workers())) {
      const what = phase.specs.length ? phase.specs.join(", ") : "every spec of the project";
      console.log(`\n== ${phase.project} phase, ${phase.workers} worker${phase.workers === 1 ? "" : "s"}: ${what}\n`);
      const done = spawnSync("bunx", ["playwright", "test", ...E2EPhases.args(phase)], { stdio: "inherit" });
      if (done.status !== 0) code = done.status ?? 1;
    }
    return code;
  }
}

if (import.meta.main) {
  const names = process.argv.slice(2);
  process.exit(E2ERun.run(names.length ? names : undefined));
}
