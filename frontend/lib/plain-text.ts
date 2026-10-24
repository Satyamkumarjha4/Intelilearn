/** Markdown with LaTeX, reduced to the plain text a PDF can print. */
export class PlainText {
  static of(markdown: string): string {
    return markdown
      .replace(/```[a-zA-Z]*\n?([\s\S]*?)```/g, "$1")
      .replace(/\$\$([\s\S]+?)\$\$/g, "$1")
      .replace(/\$([^$\n]+?)\$/g, "$1")
      .replace(/\\([a-zA-Z]+)/g, (_, name: string) => PlainText.LATEX[name] ?? name)
      .replace(/[{}]/g, "")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1$2")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/^\s*[-*]\s+/gm, "• ")
      .trim();
  }

  private static readonly LATEX: Record<string, string> = {
    log: "log",
    times: "×",
    cdot: "·",
    leq: "≤",
    geq: "≥",
    neq: "≠",
    pm: "±",
    to: "→",
    infty: "∞",
    alpha: "α",
    beta: "β",
    pi: "π",
    sum: "Σ",
    sqrt: "√",
    frac: "",
  };
}
