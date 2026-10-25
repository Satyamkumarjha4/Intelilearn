/**
 * Unit under test: `SetupMarker`, the cookie that says "this learner is in the last step of the setup".
 *
 * Why: the profile is saved at step 4, which makes the learner "onboarded" to the route guard. Without a marker the guard
 * would send a refresh on step 5 to the lesson list and throw away the topic they were choosing. The cookie is a hint
 * for the guard only (the API authorises everything), set and cleared by the page, never by the server.
 *
 * Use cases:
 * - beginning sets a session cookie for the whole site, and ending removes it
 * - it is set only while the setup runs: reading says whether it is there
 * - a page without cookies (server render, blocked storage) never throws
 */
import { describe, expect, test } from "bun:test";

import { SetupMarker } from "./setup-marker";

class FakeJar {
  written: string[] = [];
  get cookie() {
    return this.written.at(-1) ?? "";
  }
  set cookie(value: string) {
    this.written.push(value);
  }
}

describe("SetupMarker", () => {
  test("begins with a site-wide session cookie and ends by expiring it", () => {
    const jar = new FakeJar();
    const marker = new SetupMarker(jar);

    marker.begin();
    marker.end();

    expect(jar.written[0]).toBe("lc_setting_up=1; path=/; SameSite=Lax");
    expect(jar.written[1]).toStartWith("lc_setting_up=; path=/; SameSite=Lax; max-age=0");
  });

  test("never throws without a cookie jar, or with a jar that refuses", () => {
    expect(() => new SetupMarker(undefined).begin()).not.toThrow();
    const refusing = {
      get cookie(): string {
        throw new Error("blocked");
      },
      set cookie(_value: string) {
        throw new Error("blocked");
      },
    };

    expect(() => new SetupMarker(refusing).end()).not.toThrow();
  });
});
