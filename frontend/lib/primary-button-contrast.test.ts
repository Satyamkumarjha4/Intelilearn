/**
 * Unit under test: the colours of the solid primary button (`components/ui/button.tsx`, variant `default`) and of every
 * other label written in `--primary-foreground` on a teal fill, against the tokens in `app/globals.css`.
 *
 * Why: the brand teal (`--primary`) is too light to carry the white label on it (3.1:1), and button labels are small
 * text, which needs 4.5:1. Solid primary buttons therefore take their fill from the darker `--primary-action` tokens,
 * and this test fails if any pair (at rest, hovered, pressed) drops under 4.5:1 in light or dark, or if the button
 * stops using them. Every size has the same pair: sizes change the box and the type size, never the colours.
 *
 * Use cases:
 * - the fill, its hover and its pressed colour each give the label at least 4.5:1, in the light and the dark theme
 * - the edge (the flat shadow) is darker than the fill in light and different from it in dark, so the press shows
 * - the button's default variant takes its fill, hover and pressed colours from those tokens and the label from
 *   `--primary-foreground`, and keeps its colour on focus (no focus rule changes the fill)
 * - no size sets a colour of its own
 * - the general `--primary` teal is not changed by this
 * - every other fill that carries a `--primary-foreground` label (avatar initial, step numbers, badges, streak days,
 *   answer-letter chips, the sign-in side panel and its step circles, the landing page's step chips, whose insight one is `insight-text`) reads at 4.5:1
 * - no component writes `bg-primary` and `text-primary-foreground` together (the brand teal is too light for text), apart
 *   from the logo's mark, which holds a drawing and no text
 */
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { Oklch } from "./contrast";

const ROOT = join(import.meta.dir, "..");
const css = readFileSync(join(ROOT, "app/globals.css"), "utf8");
const button = readFileSync(join(ROOT, "components/ui/button.tsx"), "utf8");

/** The `--name: value;` declarations of the block that follows `selector {` (the first closing brace ends it). */
const declarations = (selector: string): Record<string, string> => {
  const start = css.indexOf(`${selector} {`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("\n}", start));
  return Object.fromEntries([...body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1]!, m[2]!.trim()]));
};

const THEMES = { light: declarations(":root"), dark: declarations(".dark") } as const;
const MIN = 4.5;

const colour = (theme: keyof typeof THEMES, token: string): Oklch => Oklch.parse(THEMES[theme][`--${token}`] ?? "");

const PAIRS: string[] = ["primary-action", "primary-action-hover", "primary-action-pressed"];

describe("solid primary button colours", () => {
  for (const theme of ["light", "dark"] as const) {
    test.each(PAIRS)(`${theme}: the label on %s is at least 4.5:1`, (fill) => {
      const ratio = Oklch.contrast(colour(theme, fill), colour(theme, "primary-foreground"));
      expect(ratio).toBeGreaterThanOrEqual(MIN);
    });
  }

  test("the edge is a visible step from the fill, so the press is seen", () => {
    expect(colour("light", "primary-action-edge").luminance()).toBeLessThan(colour("light", "primary-action").luminance());
    expect(colour("dark", "primary-action-edge").hex()).not.toBe(colour("dark", "primary-action").hex());
  });

  test("the general teal is unchanged", () => {
    expect(THEMES.light["--primary"]).toBe("oklch(0.64 0.12 190)");
    expect(THEMES.dark["--primary"]).toBe("oklch(0.76 0.12 190)");
  });
});

describe("the button uses them", () => {
  const variant = (name: string): string => new RegExp(`${name}: \`([^\`]*)\``).exec(button)?.[1] ?? "";
  const solid = variant("default");

  test("the default variant fills with the action tokens and writes the label in --primary-foreground", () => {
    expect(solid).toContain("bg-primary-action ");
    expect(solid).toContain("hover:bg-primary-action-hover");
    expect(solid).toContain("active:bg-primary-action-pressed");
    expect(solid).toContain("text-primary-foreground");
    expect(solid).toContain("var(--primary-action-edge)");
  });

  test("the lighter brand teal is never the fill, and focus leaves the fill alone", () => {
    expect(solid).not.toMatch(/(^|\s)(hover:|active:|focus[\w-]*:)?bg-primary(\/\d+)?(\s|$)/);
    expect(solid).not.toMatch(/focus[\w-]*:bg-/);
  });

  test("no size sets a fill or label colour of its own", () => {
    const sizes = /size: \{([\s\S]*?)\n      \},\n    \},\n    defaultVariants/.exec(button)?.[1] ?? "";
    expect(sizes.length).toBeGreaterThan(100);
    expect(sizes).not.toMatch(/\bbg-|text-primary|text-foreground|text-white/);
  });
});

describe("every label on a teal fill", () => {
  /** Fills that carry a `--primary-foreground` label somewhere in the app, with where. In dark, `--primary-deep` is not a
   *  fill with a label (the landing page's inset panel is `--primary-soft` with `--foreground`), so only light is held. */
  const FILLS: [string, string, string[]][] = [
    ["primary-action", "primary-foreground", ["light", "dark"]], // avatar, step numbers, badge, streak day, letter chips, side panel
    ["primary-action-pressed", "primary-foreground", ["light", "dark"]], // the side panel's step circles
    ["primary-deep", "primary-foreground", ["light"]], // the landing page's progress panel
    ["insight-text", "primary-foreground", ["light", "dark"]], // the landing page's third step chip
    ["marigold", "marigold-foreground", ["light", "dark"]], // the landing page's second step chip
  ];

  for (const [fill, label, themes] of FILLS) {
    for (const theme of themes as (keyof typeof THEMES)[]) {
      test(`${theme}: ${label} on ${fill} is at least 4.5:1`, () => {
        expect(Oklch.contrast(colour(theme, fill), colour(theme, label))).toBeGreaterThanOrEqual(MIN);
      });
    }
  }

  const sources = (dir: string): string[] =>
    readdirSync(dir).flatMap((entry) => {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) return sources(path);
      return /\.tsx$/.test(entry) ? [path] : [];
    });

  test("no class string puts text-primary-foreground on bg-primary (the logo's drawing aside)", () => {
    const BRAND_TEAL_FILL = /(?<![\w-])bg-primary(?![\w-])/;
    const LABEL = /(?<![\w-])text-primary-foreground(?![\w/-])/;
    const offenders = [...sources(join(ROOT, "components")), ...sources(join(ROOT, "app"))]
      .filter((path) => !path.endsWith("components/brand/logo.tsx"))
      .filter((path) =>
        [...readFileSync(path, "utf8").matchAll(/"[^"\n]*"|`[^`\n]*`/g)].some(
          (literal) => BRAND_TEAL_FILL.test(literal[0]) && LABEL.test(literal[0]),
        ),
      )
      .map((path) => path.slice(ROOT.length + 1));
    expect(offenders).toEqual([]);
  });
});
