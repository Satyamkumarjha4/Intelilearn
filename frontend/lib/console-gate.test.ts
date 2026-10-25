/**
 * Unit under test: `ConsoleGate`, who may see the console and what the console layout does about it.
 *
 * Why: the console is staff-only and must not announce itself. A staff member must never be bounced, a learner must see
 * the same "not found" as for any missing page (not a "forbidden" that confirms the area exists), and a signed-out
 * visitor with a stale cookie must be sent to sign in rather than shown a 404. The learner app also offers a Console
 * link, and only staff should ever see it.
 *
 * Use cases:
 * - while the session is being read, nobody is let in or turned away yet
 * - a signed-out visitor is sent to sign in, and comes back to the console page they asked for
 * - a signed-in learner (not staff) is denied
 * - a staff member is allowed
 * - the sign-in address carries the page and its query, encoded, so the return trip lands on the same view
 * - the account menu offers the console to staff only, and to nobody while the session is unknown
 */
import { describe, expect, test } from "bun:test";

import { ConsoleGate } from "./console-gate";

const staff = { is_staff: true };
const learner = { is_staff: false };

describe("ConsoleGate.decide", () => {
  test("waits while the session is being read, whoever is there", () => {
    expect(ConsoleGate.decide({ loading: true, user: null })).toBe("checking");
    expect(ConsoleGate.decide({ loading: true, user: learner })).toBe("checking");
  });

  test("sends a signed-out visitor to sign in", () => {
    expect(ConsoleGate.decide({ loading: false, user: null })).toBe("signed-out");
  });

  test("denies a learner, which the layout shows as an ordinary not-found page", () => {
    expect(ConsoleGate.decide({ loading: false, user: learner })).toBe("denied");
  });

  test("allows staff", () => {
    expect(ConsoleGate.decide({ loading: false, user: staff })).toBe("allowed");
  });
});

describe("ConsoleGate.signInHref", () => {
  test("returns to the console page that was asked for, with its filters", () => {
    expect(ConsoleGate.signInHref("/console", "")).toBe("/auth?next=%2Fconsole");
    expect(ConsoleGate.signInHref("/console/usage", "?range=30d&provider=groq")).toBe(
      "/auth?next=%2Fconsole%2Fusage%3Frange%3D30d%26provider%3Dgroq",
    );
  });
});

describe("ConsoleGate.offeredTo", () => {
  test("is true for staff only", () => {
    expect(ConsoleGate.offeredTo(staff)).toBe(true);
    expect(ConsoleGate.offeredTo(learner)).toBe(false);
    expect(ConsoleGate.offeredTo(null)).toBe(false);
    expect(ConsoleGate.offeredTo(undefined)).toBe(false);
  });
});
