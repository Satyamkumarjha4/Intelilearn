type Store = Pick<Storage, "getItem" | "setItem">;

/** Where to send a learner back to after they have bought: the last page of the app they were on before the shop (usually the
 *  lesson they could not afford), remembered in this browser tab only. Only a path of this site is ever kept. It is tracked
 *  from the page changes the app makes itself, because the browser's referrer does not change when the app moves between
 *  pages without a reload. */
export class BuyReturn {
  static readonly KEY = "socra.buy.from";
  static readonly FALLBACK = "/lessons";
  private static readonly SHOP = ["/buy", "/wallet", "/streak", "/auth", "/onboarding"];

  /** The learner is now on `path` (with its query). Pages of the shop itself, and anything that is not a path, are not kept. */
  static visit(path: string, store: Store | null): void {
    if (!path.startsWith("/") || path.startsWith("//")) return;
    const bare = path.split("?")[0];
    if (BuyReturn.SHOP.some((prefix) => bare === prefix || bare.startsWith(`${prefix}/`))) return;
    try {
      store?.setItem(BuyReturn.KEY, path);
    } catch {
      // a browser that will not store simply sends them to their lessons
    }
  }

  static recall(store: Store | null): string {
    try {
      const path = store?.getItem(BuyReturn.KEY) ?? "";
      return path.startsWith("/") && !path.startsWith("//") ? path : BuyReturn.FALLBACK;
    } catch {
      return BuyReturn.FALLBACK;
    }
  }
}
