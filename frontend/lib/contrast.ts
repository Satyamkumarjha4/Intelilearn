/**
 * WCAG contrast between two `oklch(L C h)` colours, as the design tokens in `app/globals.css` write them. Pure, so a
 * unit test can hold the palette to the 4.5:1 that text needs without a browser.
 */
export class Oklch {
  private constructor(
    readonly lightness: number,
    readonly chroma: number,
    readonly hue: number,
  ) {}

  /** Reads `oklch(0.52 0.09 195)` (the only form the tokens use); throws on anything else, so a typo cannot pass. */
  static parse(text: string): Oklch {
    const match = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)$/.exec(text.trim());
    if (!match) throw new Error(`Not an oklch() colour: ${text}`);
    return new Oklch(Number(match[1]), Number(match[2]), Number(match[3]));
  }

  /** Relative luminance (WCAG): linear sRGB, each channel clipped into the gamut, weighted. */
  luminance(): number {
    const [red, green, blue] = this.linearSrgb().map((channel) => Math.min(1, Math.max(0, channel)));
    return 0.2126 * red! + 0.7152 * green! + 0.0722 * blue!;
  }

  /** The contrast ratio of two colours, 1 to 21, whichever is the lighter. */
  static contrast(a: Oklch, b: Oklch): number {
    const [light, dark] = [a.luminance(), b.luminance()].sort((x, y) => y - x);
    return (light! + 0.05) / (dark! + 0.05);
  }

  /** The colour as `#RRGGBB`, for reports. */
  hex(): string {
    return (
      "#" +
      this.linearSrgb()
        .map((channel) => {
          const clipped = Math.min(1, Math.max(0, channel));
          const encoded = clipped <= 0.0031308 ? 12.92 * clipped : 1.055 * clipped ** (1 / 2.4) - 0.055;
          return Math.round(encoded * 255).toString(16).padStart(2, "0");
        })
        .join("")
        .toUpperCase()
    );
  }

  private linearSrgb(): [number, number, number] {
    const a = this.chroma * Math.cos((this.hue * Math.PI) / 180);
    const b = this.chroma * Math.sin((this.hue * Math.PI) / 180);
    const l = (this.lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (this.lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (this.lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
    return [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
    ];
  }
}
