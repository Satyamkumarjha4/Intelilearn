type NavigatorLike = { clipboard?: { writeText(text: string): Promise<void> } };
type DocumentLike = Pick<Document, "createElement" | "body" | "execCommand">;

/** Copies text. The modern API needs a secure page and a permission; when it is missing or refused, a hidden text box is
 *  selected and copied the old way. Says whether either worked, so the page can fall back to "select it yourself". */
export class Clipboard {
  constructor(
    private readonly nav: NavigatorLike = typeof navigator === "undefined" ? {} : navigator,
    private readonly doc: DocumentLike | null = typeof document === "undefined" ? null : document,
  ) {}

  async copy(text: string): Promise<boolean> {
    try {
      if (this.nav.clipboard) {
        await this.nav.clipboard.writeText(text);
        return true;
      }
    } catch {
      // refused: try the old way
    }
    return this.copyBySelection(text);
  }

  private copyBySelection(text: string): boolean {
    if (!this.doc) return false;
    const box = this.doc.createElement("textarea");
    box.value = text;
    box.setAttribute("readonly", "");
    box.style.position = "fixed";
    box.style.opacity = "0";
    this.doc.body.appendChild(box);
    try {
      box.select();
      return this.doc.execCommand("copy");
    } catch {
      return false;
    } finally {
      box.remove();
    }
  }
}
