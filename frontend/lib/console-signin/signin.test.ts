/**
 * Unit under test: `ReasonForm`, `SigninWords`, `AbuseSummary` (`lib/console-signin/forms.ts`), `SigninFailure`
 * (`failure.ts`), `SigninQueries` (`queries.ts`) and the sign-in calls of `ConsoleApi`.
 *
 * Why: vouching for a person without a reason, printing a raw code in front of a maintainer, or asking the wrong path
 * for a sign-up would each be a mistake in the one place support uses to help someone who is stuck. The words must say
 * what the API's codes mean, the reason rule must match the server's, and the paths and bodies must be exact.
 *
 * Use cases:
 * - a reason needs 10 characters after trimming, and at most 500
 * - every source, code state, purpose, method and refusal code has words; an unknown one is passed on; the ways to sign in
 *   read as a sentence, and a person with none is told how they can get one
 * - times read in UTC; a missing or bad time is empty
 * - the abuse totals add the days, and a chart of quiet days has a peak of at least 1
 * - a refused action is explained from its 409 code, a missing reason from the 400's field, and anything else is left to
 *   the general message
 * - the queries are keyed under "console", page signups by cursor after the trimmed search, and read the verification
 *   panel and the abuse board
 * - the API calls use the exact paths, methods and bodies (the reason travels as `reason`)
 */
import { describe, expect, test } from "bun:test";

import { ApiError, type ApiClient, type RequestOptions } from "@/lib/api";
import { ConsoleApi } from "@/lib/console-api";

import { SigninFailure } from "./failure";
import { AbuseSummary, ReasonForm, SigninWords } from "./forms";
import { SigninQueries } from "./queries";

describe("ReasonForm", () => {
  test.each([
    ["", true],
    ["too short", true],
    ["          ", true],
    ["Spoke to the teacher", false],
    ["  ten chars!  ", false],
    ["x".repeat(501), true],
    ["x".repeat(500), false],
  ])("%p is refused: %p", (text, refused) => {
    expect(ReasonForm.error(text) !== undefined).toBe(refused);
  });
});

describe("SigninWords", () => {
  test("every source and code state has words, and an unknown one is passed on", () => {
    for (const source of ["code", "google", "microsoft", "staff", "operator", "legacy", ""]) expect(SigninWords.source(source)).not.toBe(source || "x");
    for (const state of ["live", "used", "cancelled", "dead", "expired"]) expect(SigninWords.codeState(state)).not.toBe(state);
    expect(SigninWords.source("newcomer")).toBe("newcomer");
    expect(SigninWords.codeState("odd")).toBe("odd");
  });

  test("purposes and methods have words", () => {
    expect(SigninWords.purpose("login")).toBe("Sign-in");
    expect(SigninWords.method("google")).toBe("Google");
  });

  test("a refusal code has words and an unknown one keeps the server's sentence", () => {
    expect(SigninWords.refusal("already_verified", "x")).toBe("This account is already verified.");
    expect(SigninWords.refusal("nothing_to_unlock", "x")).toContain("Nothing to unlock");
    expect(SigninWords.refusal("brand_new", "the server's own")).toBe("the server's own");
    expect(SigninWords.refusal(undefined, "fallback")).toBe("fallback");
  });

  test("the ways to sign in read as a sentence", () => {
    expect(SigninWords.methods(["password"])).toBe("Password");
    expect(SigninWords.methods(["password", "google"])).toBe("Password and Google");
    expect(SigninWords.methods(["password", "google", "microsoft"])).toBe("Password, Google and Microsoft");
    expect(SigninWords.methods([])).toContain("Forgot password");
  });

  test("times read in UTC, and a missing or bad time is empty", () => {
    expect(SigninWords.when("2026-03-15T12:30:00Z")).toBe("15 Mar, 12:30");
    expect(SigninWords.when(null)).toBe("");
    expect(SigninWords.when("not a time")).toBe("");
  });
});

describe("AbuseSummary", () => {
  const day = (n: number) => ({ accounts_made: n, codes_sent: n * 2, failed_checks: 1, disposable_refused: 0, captcha_failed: n });

  test("totals add the days", () => {
    expect(AbuseSummary.totals([day(1), day(2)])).toEqual({ accounts_made: 3, codes_sent: 6, failed_checks: 2, disposable_refused: 0, captcha_failed: 3 });
    expect(AbuseSummary.totals([]).accounts_made).toBe(0);
  });

  test("the peak is never below 1", () => {
    expect(AbuseSummary.peak([0, 0])).toBe(1);
    expect(AbuseSummary.peak([3, 9, 2])).toBe(9);
  });
});

describe("SigninFailure.message", () => {
  test("explains a refused action from its code", () => {
    expect(SigninFailure.message(new ApiError(409, "account_closed", "closed"))).toBe("This account is closed.");
    expect(SigninFailure.message(new ApiError(409, "something_new", "The server says so"))).toBe("The server says so");
  });

  test("says what is wrong with the reason", () => {
    expect(SigninFailure.message(new ApiError(400, "invalid", "x", { reason: ["Say why, in at least 10 characters."] }))).toBe("Say why, in at least 10 characters.");
  });

  test("leaves anything else to the general message", () => {
    expect(SigninFailure.message(new ApiError(500, "error", "boom"))).toBeUndefined();
    expect(SigninFailure.message(new Error("network"))).toBeUndefined();
    expect(SigninFailure.message(new ApiError(400, "invalid", "x", { other: ["y"] }))).toBeUndefined();
  });
});

type Call = { path: string; options?: RequestOptions };

function fakeApi() {
  const calls: Call[] = [];
  const client = {
    request: async (path: string, options?: RequestOptions) => {
      calls.push({ path, options });
      return { next: null, results: [] };
    },
    refreshSession: async () => false,
  } as unknown as ApiClient;
  return { api: new ConsoleApi(client), calls };
}

describe("ConsoleApi sign-in calls", () => {
  test("a learner's verification: read, resend, unlock, mark verified with the reason", async () => {
    const { api, calls } = fakeApi();

    await api.verification("L1");
    await api.resendVerification("L1");
    await api.unlockVerification("L1");
    await api.markVerified("L1", "Spoke to the teacher");

    expect(calls).toEqual([
      { path: "/console/learners/L1/verification", options: { method: "GET" } },
      { path: "/console/learners/L1/verification/resend", options: { method: "POST" } },
      { path: "/console/learners/L1/verification/unlock", options: { method: "POST" } },
      { path: "/console/learners/L1/verification/mark-verified", options: { method: "POST", body: { reason: "Spoke to the teacher" } } },
    ]);
  });

  test("the sign-ups waiting: list (trimmed search, cursor), resend, unlock and approve with the reason", async () => {
    const { api, calls } = fakeApi();

    await api.signups({ q: " ada ", cursor: "c1", pageSize: 25 });
    await api.signups();
    await api.resendSignup("S1");
    await api.unlockSignup("S1");
    await api.approveSignup("S1", "Confirmed by phone");

    expect(calls.map((c) => [c.options?.method, c.path])).toEqual([
      ["GET", "/console/signups?q=ada&cursor=c1&page_size=25"],
      ["GET", "/console/signups"],
      ["POST", "/console/signups/S1/resend"],
      ["POST", "/console/signups/S1/unlock"],
      ["POST", "/console/signups/S1/approve"],
    ]);
    expect(calls[4].options?.body).toEqual({ reason: "Confirmed by phone" });
  });

  test("the abuse board is read, and the challenge switch is read and put", async () => {
    const { api, calls } = fakeApi();

    await api.abuse();
    await api.authSettings();
    await api.setCaptcha(true);

    expect(calls.map((c) => [c.options?.method, c.path])).toEqual([
      ["GET", "/console/abuse"],
      ["GET", "/console/auth-settings"],
      ["PUT", "/console/auth-settings"],
    ]);
    expect(calls[2].options?.body).toEqual({ captcha_enabled: true });
  });
});

describe("SigninQueries", () => {
  function queries() {
    const seen: unknown[] = [];
    const api = {
      verification: async (id: string) => (seen.push(["verification", id]), {}),
      signups: async (arg: unknown) => (seen.push(["signups", arg]), { next: "http://backend/api/console/signups?cursor=zz", results: [] }),
      abuse: async () => (seen.push(["abuse"]), {}),
    } as unknown as ConsoleApi;
    return { seen, queries: new SigninQueries(api) };
  }

  test("keys are under console, and a search is its own entry", () => {
    const { queries: q } = queries();

    const key = (options: { queryKey: unknown }): unknown => options.queryKey;

    expect(key(q.verification("L1"))).toEqual(["console", "verification", "L1"]);
    expect(key(q.abuse())).toEqual(["console", "abuse"]);
    expect(key(q.signups("  ada "))).toEqual(["console", "signups", "ada"]);
    expect(key(q.signups(""))).toEqual(key(q.signups("   ")));
  });

  test("signups page by the cursor of the next link, 25 at a time", async () => {
    const { queries: q, seen } = queries();
    const options = q.signups("ada") as unknown as {
      queryFn: (c: { pageParam: string | null }) => Promise<{ next: string | null }>;
      getNextPageParam: (last: { next: string | null }) => unknown;
    };

    const page = await options.queryFn({ pageParam: "c0" });

    expect(seen).toEqual([["signups", { q: "ada", cursor: "c0", pageSize: 25 }]]);
    expect(options.getNextPageParam(page)).toBe("zz");
    expect(options.getNextPageParam({ next: null })).toBeUndefined();
  });

  test("the verification panel and the abuse board are read through the api", async () => {
    const { queries: q, seen } = queries();

    await (q.verification("L1") as unknown as { queryFn: () => Promise<unknown> }).queryFn();
    await (q.abuse() as unknown as { queryFn: () => Promise<unknown> }).queryFn();

    expect(seen).toEqual([["verification", "L1"], ["abuse"]]);
  });
});
