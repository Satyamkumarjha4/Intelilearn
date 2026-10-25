export type NavIcon = "overview" | "usage" | "runs" | "models" | "routing" | "settings" | "learners" | "audit";
export type NavItem = { key: NavIcon; label: string; href: string };
export type NavSection = { label: string; items: NavItem[] };

/** The console's sidebar. The labels are the screens' names; the order is how a maintainer works: look, then change. */
export class ConsoleNav {
  static readonly SECTIONS: readonly NavSection[] = [
    {
      label: "Monitor",
      items: [
        { key: "overview", label: "Overview", href: "/console" },
        { key: "usage", label: "Usage & cost", href: "/console/usage" },
        { key: "runs", label: "Lesson runs", href: "/console/runs" },
      ],
    },
    {
      label: "Configure",
      items: [
        { key: "models", label: "Models", href: "/console/models" },
        { key: "routing", label: "Model routing", href: "/console/routing" },
        { key: "settings", label: "Lesson settings", href: "/console/settings" },
      ],
    },
    {
      label: "People",
      items: [
        { key: "learners", label: "Learners", href: "/console/learners" },
        { key: "audit", label: "Change log", href: "/console/audit" },
      ],
    },
  ];

  static items(): NavItem[] {
    return ConsoleNav.SECTIONS.flatMap((section) => section.items);
  }

  /** Whether a link is the page being shown: the overview only on its own address, the others also below it. */
  static isCurrent(href: string, pathname: string): boolean {
    const path = pathname.replace(/\/+$/, "") || "/";
    return href === "/console" ? path === "/console" : path === href || path.startsWith(`${href}/`);
  }

  /** The item for a path, if it is one of the console's pages. */
  static itemFor(pathname: string): NavItem | undefined {
    return ConsoleNav.items().find((item) => ConsoleNav.isCurrent(item.href, pathname));
  }

  /** The number on a badge: nothing for zero, the count up to 99, then "99+". */
  static badge(count: number | undefined): string | null {
    if (!count || count < 1) return null;
    return count > 99 ? "99+" : String(count);
  }
}
