/**
 * Unit under test: `E2EPhases`, which splits the e2e specs to run into the serial phase and the parallel one.
 *
 * Why: most specs make their own learner and touch nothing shared, so they can run side by side (a lesson build is the slow
 * part, and it is mostly waiting). A few change what every learner sees (the price table, the credit settings, the list of
 * testimonials, the console's views of them), and they must not run while another worker reads those: they run first, alone.
 * A spec put in the wrong phase gives a failure that only shows now and then, so the split is one list, tested.
 *
 * Use cases:
 * - a full run is the serial phase, one worker, and then the parallel phase, with the workers asked for
 * - the serial phase has the specs that change shared state; every other spec is in the parallel phase
 * - a chosen set is split the same way, and a phase with no spec in it is left out
 * - the parallel phase does not repeat the warm-up when the serial phase has run it, and does run it when it is first
 * - the specs that need a live provider are in the serial project too, so running one by name finds it
 */
import { describe, expect, test } from "bun:test";

import { E2EPhases } from "./support/phases";

const ALL = [
  "console-credits.spec.ts", "console.spec.ts", "credits.spec.ts", "followups.spec.ts", "journey.spec.ts", "landing.spec.ts",
  "payments-razorpay.spec.ts", "payments-stripe.spec.ts", "payments.spec.ts", "quizzes.spec.ts", "self-rating.spec.ts",
  "sheets.spec.ts", "stop-and-retry.spec.ts", "timezone.spec.ts", "onboarding-refresh.spec.ts",
]; // prettier-ignore

describe("E2EPhases", () => {
  test("a full run is the serial phase on one worker, then the parallel phase on the workers asked for", () => {
    expect(E2EPhases.plan(undefined, 4)).toEqual([
      { project: "global", specs: [], workers: 1, warmUp: true },
      { project: "learner", specs: [], workers: 4, warmUp: false },
    ]);
  });

  test("the specs that change shared state are the serial ones", () => {
    expect(E2EPhases.SERIAL).toEqual(["console-credits.spec.ts", "console.spec.ts", "credits.spec.ts", "landing.spec.ts"]);
  });

  test("a chosen set is split, and the parallel phase runs the others", () => {
    const phases = E2EPhases.plan(["credits.spec.ts", "journey.spec.ts", "quizzes.spec.ts", "landing.spec.ts"], 3);

    expect(phases).toEqual([
      { project: "global", specs: ["credits.spec.ts", "landing.spec.ts"], workers: 1, warmUp: true },
      { project: "learner", specs: ["journey.spec.ts", "quizzes.spec.ts"], workers: 3, warmUp: false },
    ]);
  });

  test("a phase with no spec in it is left out, and the one that remains does the warm-up", () => {
    expect(E2EPhases.plan(["journey.spec.ts"], 4)).toEqual([{ project: "learner", specs: ["journey.spec.ts"], workers: 4, warmUp: true }]);
    expect(E2EPhases.plan(["console.spec.ts"], 4)).toEqual([{ project: "global", specs: ["console.spec.ts"], workers: 1, warmUp: true }]);
  });

  test("no spec chosen is nothing to run, not a full run", () => {
    expect(E2EPhases.plan([], 4)).toEqual([]);
  });

  test("workers is at least one", () => {
    expect(E2EPhases.plan(["journey.spec.ts"], 0)[0]!.workers).toBe(1);
    expect(E2EPhases.plan(["journey.spec.ts"], Number.NaN)[0]!.workers).toBe(1);
  });

  test("the live-provider specs belong to the serial project, but a run by selection never picks them", () => {
    expect(E2EPhases.MANUAL).toEqual(["payments-razorpay.spec.ts", "payments-stripe.spec.ts"]);
    expect(E2EPhases.SERIAL).not.toContain("payments-stripe.spec.ts");
    expect(E2EPhases.projectOf("payments-stripe.spec.ts")).toBe("global");
    expect(E2EPhases.projectOf("journey.spec.ts")).toBe("learner");
    expect(ALL.filter((spec) => E2EPhases.projectOf(spec) === "global")).toEqual([...E2EPhases.SERIAL, ...E2EPhases.MANUAL].sort());
  });

  test("the argument Playwright takes for a spec file is its path under tests", () => {
    expect(E2EPhases.args({ project: "global", specs: ["credits.spec.ts"], workers: 1, warmUp: true })).toEqual([
      "--project=global",
      "--workers=1",
      "tests/credits.spec.ts",
    ]);
    expect(E2EPhases.args({ project: "learner", specs: [], workers: 4, warmUp: false })).toEqual(["--project=learner", "--workers=4", "--no-deps"]);
  });
});
