/** The three pages of a lesson, and the links that open one of them (plan §9.6). The lesson tab is `?tab=lesson`, and
 * `page=` says which page of the book to open; a link without a page opens the lesson at its first page. */
export class PageLinks {
  /** The pages of the book, in the order the document has them. */
  static readonly KEYS = ["introduction", "core", "advanced"] as const;

  /** The place of a page in the book (0, 1 or 2), or null when it is not a page of a lesson. */
  static indexOf(key: string | null | undefined): number | null {
    const found = PageLinks.KEYS.findIndex((candidate) => candidate === key);
    return found < 0 ? null : found;
  }

  /** The page to open from the address bar's `page=`; the same rule as `indexOf`. */
  static fromQuery(value: string | null): number | null {
    return PageLinks.indexOf(value);
  }

  /** Where "Study this" goes: the page of the lesson, or the lesson when the concept could not be placed. */
  static href(lessonId: string, page: string | null | undefined): string {
    const base = `/lessons/${lessonId}?tab=lesson`;
    return PageLinks.indexOf(page) === null ? base : `${base}&page=${page}`;
  }

  /** "Core page · How halving works": where in the lesson the concept is taught; empty when it has no page. */
  static where(link: { page: string; heading: string }): string {
    if (PageLinks.indexOf(link.page) === null) return "";
    const page = `${link.page.charAt(0).toUpperCase()}${link.page.slice(1)} page`;
    return link.heading ? `${page} · ${link.heading}` : page;
  }

  /** What the button says: "Study this" for a page, "Open the lesson" when there is no page to send them to. */
  static button(link: { page: string }): string {
    return PageLinks.indexOf(link.page) === null ? "Open the lesson" : "Study this";
  }

  /** The "Study this" link for one topic of a lesson's own test result, from the links the server sent with it. */
  static study(
    lessonId: string,
    links: readonly { concept: string; page: string; heading: string }[] | undefined,
    topic: string,
  ): { href: string; where: string; button: string } {
    const link = links?.find((candidate) => candidate.concept === topic) ?? { page: "", heading: "" };
    return { href: PageLinks.href(lessonId, link.page), where: PageLinks.where(link), button: PageLinks.button(link) };
  }
}
