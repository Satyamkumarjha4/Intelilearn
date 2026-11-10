/**
 * Unit under test: `PublicLanding`, the Next server's reader of `/api/public/testimonials` and `/api/public/pricing`.
 *
 * Why: the front page must always load. A testimonial list that cannot be read is an empty one (the page shows the
 * maker's note), a price list that cannot be read is nothing (the page shows no number), and neither a slow API, an error
 * nor a half-formed answer may break the page or put "undefined" on it. Answers are never cached here, so a change made in
 * the console shows on the next load.
 *
 * Use cases:
 * - testimonials are read from the right path, with no cache and the visitor's address passed on when known
 * - rows without a name or a quote are dropped, a rating that is not a number is none, an answer that is not a list is empty
 * - a failing API, a bad status, a thrown fetch or a body that is not JSON give no testimonials and no pricing
 * - the pricing is returned when it has every number the page needs, and is null when one is missing or the wrong kind
 * - a price the server left null (no live price) is accepted as null
 */
import { describe, expect, test } from "bun:test";

import { pricing } from "./fixtures";
import { PublicLanding } from "./public-landing";

type Call = { url: string; init: RequestInit };

function landing(respond: (url: string) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetcher = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return respond(url);
  }) as unknown as typeof fetch;
  return { reader: new PublicLanding(fetcher, "http://api"), calls };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("testimonials", () => {
  test("read from the public path, uncached, as the visitor", async () => {
    const { reader, calls } = landing(() => json({ testimonials: [{ name: "Asha Rao", context: "Class 12 student", quote: "Good.", rating: 5 }] }));

    const rows = await reader.testimonials({ clientIp: "203.0.113.9" });

    expect(rows).toEqual([{ name: "Asha Rao", context: "Class 12 student", quote: "Good.", rating: 5 }]);
    expect(calls[0].url).toBe("http://api/api/public/testimonials");
    expect(calls[0].init.cache).toBe("no-store");
    expect(calls[0].init.headers).toEqual({ "x-forwarded-for": "203.0.113.9" });
  });

  test("rows missing a name or a quote are dropped and a bad rating is none", async () => {
    const { reader } = landing(() =>
      json({ testimonials: [{ name: "", quote: "x", context: "c", rating: 5 }, { name: "A", quote: " ", context: "c", rating: 5 }, { name: "B", quote: "q", context: "c", rating: "5" }, 7] }),
    );

    expect(await reader.testimonials()).toEqual([{ name: "B", context: "c", quote: "q", rating: null }]);
  });

  test("an answer that is not a list is an empty list", async () => {
    const { reader } = landing(() => json({ testimonials: "nope" }));

    expect(await reader.testimonials()).toEqual([]);
  });

  test.each([
    ["a bad status", () => json({}, 500)],
    ["a body that is not JSON", () => new Response("<html>", { status: 200 })],
    ["a thrown fetch", () => Promise.reject(new Error("down"))],
  ])("%s gives none", async (_name, respond) => {
    const { reader } = landing(respond as () => Response);

    expect(await reader.testimonials()).toEqual([]);
    expect(await reader.pricing()).toBeNull();
  });
});

describe("pricing", () => {
  test("a complete answer is returned as it is", async () => {
    const { reader, calls } = landing(() => json(pricing()));

    expect(await reader.pricing()).toEqual(pricing());
    expect(calls[0].url).toBe("http://api/api/public/pricing");
  });

  test("a price the server left null is accepted", async () => {
    const body = pricing({ retake_credits: null, sheet_credits: null, lesson_credits: null, signup_about_lessons: null, one_time: null });
    const { reader } = landing(() => json(body));

    expect(await reader.pricing()).toEqual(body);
  });

  test.each([
    ["a missing number", { signup_credits: undefined }],
    ["a number that is text", { daily_credits: "1" }],
    ["a negative number", { weekly_streak_bonus: -1 }],
    ["plans that are not a list", { plans: {} }],
    ["a plan without a name", { plans: [{ ...pricing().plans[0], name: "" }] }],
    ["a range that is half there", { quiz_credits: { min: 1 } }],
  ])("%s is not pricing", async (_name, change) => {
    const { reader } = landing(() => json({ ...pricing(), ...change }));

    expect(await reader.pricing()).toBeNull();
  });
});
