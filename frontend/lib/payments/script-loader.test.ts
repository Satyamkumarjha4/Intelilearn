/**
 * Unit under test: `ScriptLoader` and `BrowserScripts`, which load a provider's script when it is first needed (credits
 * plan §9.4).
 *
 * Why: Razorpay's script is third-party code, so it must not be on every page, and must not be added twice when a learner
 * presses Buy more than once. A failure to load (a blocked network, an ad blocker) must be a clear, recoverable error,
 * not a button that never works again.
 *
 * Use cases:
 * - nothing is loaded until `load` is called; a script whose work is already there is not loaded at all
 * - the first call loads it; a second call while it loads shares the first, and one after it has loaded loads nothing
 * - a script that fails to load is `CheckoutUnavailable`, and the next call tries again from clean
 * - a script that loads but does not do what it should (its global is missing) is `CheckoutUnavailable` too
 * - the browser's way of loading: an async script at the end of the body, removed again when it fails
 */
import { describe, expect, test } from "bun:test";

import { CheckoutUnavailable } from "./checkout-contract";
import { BrowserScripts, ScriptLoader, type ScriptInjector } from "./script-loader";

/** An injector the test finishes by hand. */
function injector() {
  const asked: { src: string; ok: () => void; fail: () => void }[] = [];
  const inject: ScriptInjector = (src, ok, fail) => void asked.push({ src, ok, fail });
  return { asked, inject };
}

describe("ScriptLoader", () => {
  test("loads nothing until it is asked, and nothing at all when the work is already there", async () => {
    const { asked, inject } = injector();
    const loader = new ScriptLoader(inject);
    expect(asked).toHaveLength(0);

    await loader.load("https://x.test/a.js", () => true);

    expect(asked).toHaveLength(0);
  });

  test("the first call loads the script, a second while it loads shares it, and a later one does nothing", async () => {
    const { asked, inject } = injector();
    let ready = false;
    const loader = new ScriptLoader(inject);

    const first = loader.load("https://x.test/a.js", () => ready);
    const second = loader.load("https://x.test/a.js", () => ready);
    expect(asked).toHaveLength(1);
    ready = true;
    asked[0].ok();
    await Promise.all([first, second]);
    await loader.load("https://x.test/a.js", () => ready);

    expect(asked).toHaveLength(1);
    expect(asked[0].src).toBe("https://x.test/a.js");
  });

  test("a failure is CheckoutUnavailable, and the next call tries again", async () => {
    const { asked, inject } = injector();
    let ready = false;
    const loader = new ScriptLoader(inject);

    const failed = loader.load("https://x.test/a.js", () => ready);
    asked[0].fail();
    await expect(failed).rejects.toBeInstanceOf(CheckoutUnavailable);

    const again = loader.load("https://x.test/a.js", () => ready);
    expect(asked).toHaveLength(2);
    ready = true;
    asked[1].ok();
    await again;
  });

  test("a script that loads but leaves nothing behind is CheckoutUnavailable", async () => {
    const { asked, inject } = injector();
    const loader = new ScriptLoader(inject);

    const loading = loader.load("https://x.test/a.js", () => false);
    asked[0].ok();

    await expect(loading).rejects.toThrow("did not start");
  });
});

describe("BrowserScripts", () => {
  function fakeDocument() {
    const appended: Record<string, unknown>[] = [];
    const doc = {
      createElement: () => {
        const script: Record<string, unknown> = { removed: false };
        script.remove = () => (script.removed = true);
        return script;
      },
      body: { appendChild: (node: Record<string, unknown>) => void appended.push(node) },
    };
    return { doc: doc as unknown as Document, appended };
  }

  test("adds an async script at the end of the body", () => {
    const { doc, appended } = fakeDocument();

    new BrowserScripts(doc).inject("https://x.test/a.js", () => {}, () => {});

    expect(appended).toHaveLength(1);
    expect(appended[0]).toMatchObject({ src: "https://x.test/a.js", async: true });
  });

  test("says when it has loaded", () => {
    const { doc, appended } = fakeDocument();
    let loaded = 0;
    new BrowserScripts(doc).inject("https://x.test/a.js", () => loaded++, () => {});

    (appended[0].onload as () => void)();

    expect(loaded).toBe(1);
  });

  test("says when it failed, and takes the script out again", () => {
    const { doc, appended } = fakeDocument();
    let failed = 0;
    new BrowserScripts(doc).inject("https://x.test/a.js", () => {}, () => failed++);

    (appended[0].onerror as () => void)();

    expect(failed).toBe(1);
    expect(appended[0].removed).toBe(true);
  });

  test("looks the document up when it is used, not when it is made", () => {
    const { doc, appended } = fakeDocument();
    const scripts = new BrowserScripts(() => doc);

    scripts.inject("https://x.test/a.js", () => {}, () => {});

    expect(appended).toHaveLength(1);
  });
});
