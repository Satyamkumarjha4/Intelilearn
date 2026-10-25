export type ClickInfo = {
  /** The link's absolute address (`anchor.href`), or null for a click that was not on a link. */
  href: string | null;
  target: string;
  download: boolean;
  button: number;
  /** Ctrl, Meta, Shift or Alt was held. */
  modified: boolean;
  /** Something else already handled the click (`defaultPrevented`). */
  handled: boolean;
};

/**
 * Whether a click would leave a page that has unsaved changes. Only a plain click that goes to another page of this
 * site is stopped; everything the browser handles itself (a new tab, a download, another site) is left alone.
 */
export class UnsavedGuard {
  /** The path (with query and hash) the click goes to when it should be confirmed first; otherwise null. */
  static destination(click: ClickInfo, here: { origin: string; pathname: string }): string | null {
    if (click.handled || !click.href || click.download || click.modified || click.button !== 0) return null;
    if (click.target && click.target !== "_self") return null;
    let url: URL;
    try {
      url = new URL(click.href);
    } catch {
      return null;
    }
    if (url.origin !== here.origin || url.pathname === here.pathname) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  }
}
