/**
 * Unit under test: the design tokens in `app/globals.css` and their copy in the lesson sandbox's harness page
 * (`sandbox/src/harness.html`), plus the rule that components take their colours from tokens.
 *
 * Why: the generated lesson runs in an iframe with its own copy of the palette (the app only tells it "light" or
 * "dark"), so the two drift apart silently unless something compares them. A raw `emerald-600` in a component
 * ignores the brand palette and the dark theme.
 *
 * Use cases:
 * - every brand token exists in the light (:root) and dark (.dark) palettes and is registered for Tailwind utilities
 * - every colour the harness declares has the app's value, in both light and dark
 * - the harness declares every brand token, so generated lessons can use them
 * - no component or sandbox scope file uses a raw Tailwind palette colour
 */
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(import.meta.dir, "..");
const GLOBALS = join(ROOT, "app/globals.css");
const HARNESS = join(ROOT, "../sandbox/src/harness.html");

/** The brand tokens added on top of the shadcn names (primary, destructive, … already exist). */
const BRAND_TOKENS = [
  "paper",
  "primary-deep",
  "primary-soft",
  "primary-text",
  "marigold",
  "marigold-foreground",
  "marigold-deep",
  "marigold-soft",
  "marigold-text",
  "insight",
  "insight-soft",
  "insight-text",
  "success",
  "success-soft",
  "success-text",
  "destructive-soft",
  "destructive-text",
];

/** Reads `--name: value;` declarations out of the CSS block that follows a selector. */
class CssBlocks {
  constructor(private readonly css: string) {}

  /** The text between the braces after `selector {` (first match), or null. */
  body(selector: string): string | null {
    const start = this.css.indexOf(`${selector} {`);
    if (start === -1) return null;
    let depth = 0;
    for (let i = this.css.indexOf("{", start); i < this.css.length; i++) {
      if (this.css[i] === "{") depth++;
      if (this.css[i] === "}" && --depth === 0) return this.css.slice(this.css.indexOf("{", start) + 1, i);
    }
    return null;
  }

  /** `{name: value}` for every custom property declared in the block. */
  declarations(selector: string): Record<string, string> {
    const found: Record<string, string> = {};
    for (const match of (this.body(selector) ?? "").matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) found[match[1]!] = match[2]!.trim();
    return found;
  }
}

const globals = new CssBlocks(readFileSync(GLOBALS, "utf8"));
const harness = new CssBlocks(readFileSync(HARNESS, "utf8"));

const appLight = globals.declarations(":root");
const appDark = globals.declarations(".dark");
const registered = globals.declarations("@theme inline");
const harnessLight = harness.declarations("@theme");
const harnessDark = harness.declarations(":root.dark");

describe("brand tokens in globals.css", () => {
  test.each(BRAND_TOKENS)("%s is defined for light and dark and registered as a Tailwind colour", (name) => {
    expect(appLight[`--${name}`]).toBeDefined();
    expect(appDark[`--${name}`]).toBeDefined();
    expect(registered[`--color-${name}`]).toBe(`var(--${name})`);
  });
});

describe("sandbox harness palette", () => {
  test("declares colours at all", () => {
    expect(Object.keys(harnessLight).length).toBeGreaterThan(0);
  });

  test.each(BRAND_TOKENS)("declares %s, so generated lessons can use it", (name) => {
    expect(harnessLight[`--color-${name}`]).toBeDefined();
    expect(harnessDark[`--color-${name}`]).toBeDefined();
  });

  test("every light colour is the app's light colour", () => {
    for (const [name, value] of Object.entries(harnessLight)) {
      if (!name.startsWith("--color-")) continue;
      expect([name, value]).toEqual([name, appLight[`--${name.slice("--color-".length)}`]]);
    }
  });

  test("every colour has a dark value, and it is the app's dark colour", () => {
    for (const name of Object.keys(harnessLight)) {
      if (!name.startsWith("--color-")) continue;
      expect([name, harnessDark[name]]).toEqual([name, appDark[`--${name.slice("--color-".length)}`]]);
    }
  });
});

describe("raw palette colours", () => {
  const RAW = /\b(?:emerald|zinc|green|red|gray|slate|stone|neutral|sky|blue|amber|yellow|orange|violet|purple)-\d{2,3}\b/;

  const sources = (dir: string): string[] =>
    readdirSync(dir).flatMap((entry) => {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) return sources(path);
      return /\.(tsx?|css)$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
    });

  test("components and sandbox scope files use tokens", () => {
    const offenders = [...sources(join(ROOT, "components")), ...sources(join(ROOT, "../sandbox/src/scope"))].filter((path) =>
      RAW.test(readFileSync(path, "utf8")),
    );
    expect(offenders).toEqual([]);
  });
});
