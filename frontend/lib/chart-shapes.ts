export type RoundedCorners = "top" | "right" | "none";

/** The outline of a bar segment. In a stack only the outermost segment is rounded (at the top of a column, at the
 *  right end of a row), so the segments meet in straight lines with a gap between them. */
export class RoundedRect {
  static path(x: number, y: number, width: number, height: number, radius: number, corners: RoundedCorners): string {
    if (!(width > 0) || !(height > 0)) return "";
    const r = corners === "none" ? 0 : Math.max(0, Math.min(radius, width / 2, corners === "right" ? height / 2 : height));
    const right = x + width;
    const bottom = y + height;
    if (corners === "top" && r > 0) {
      return `M${x} ${bottom} V${y + r} A${r} ${r} 0 0 1 ${x + r} ${y} H${right - r} A${r} ${r} 0 0 1 ${right} ${y + r} V${bottom} Z`;
    }
    if (corners === "right" && r > 0) {
      return `M${x} ${y} H${right - r} A${r} ${r} 0 0 1 ${right} ${y + r} V${bottom - r} A${r} ${r} 0 0 1 ${right - r} ${bottom} H${x} Z`;
    }
    return `M${x} ${y} H${right} V${bottom} H${x} Z`;
  }
}
