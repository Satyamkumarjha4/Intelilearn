"use client";

import {
  ActivityIcon,
  ArrowLeftIcon,
  CircleDollarSignIcon,
  CpuIcon,
  LayoutDashboardIcon,
  type LucideIcon,
  RouteIcon,
  ScrollTextIcon,
  SlidersHorizontalIcon,
  UsersIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand/logo";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { ThemeToggle } from "@/components/theme-toggle";
import { ConsoleNav, type NavIcon } from "@/lib/console-nav";
import { consoleQueries } from "@/lib/console-queries";
import { Initials } from "@/lib/initials";
import { cn } from "@/lib/utils";

const ICONS: Record<NavIcon, LucideIcon> = {
  overview: LayoutDashboardIcon,
  usage: CircleDollarSignIcon,
  runs: ActivityIcon,
  models: CpuIcon,
  routing: RouteIcon,
  settings: SlidersHorizontalIcon,
  learners: UsersIcon,
  audit: ScrollTextIcon,
};

/** The console's menu: a sticky column on a wide screen, a sideways-scrolling bar across the top below 900 px. */
export function ConsoleSidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const failed = useConsoleQuery(consoleQueries.failedRuns()).data;

  return (
    <aside
      aria-label="Console navigation"
      className="sticky top-0 flex h-screen flex-col gap-1 border-r bg-sidebar px-3.5 py-[18px] max-[900px]:z-10 max-[900px]:h-auto max-[900px]:flex-row max-[900px]:items-center max-[900px]:gap-1 max-[900px]:overflow-x-auto max-[900px]:border-r-0 max-[900px]:border-b max-[900px]:px-3 max-[900px]:py-2"
    >
      <Link href="/console" aria-label="Socra Console home" className="mb-3 flex items-center rounded-lg px-2 py-1 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 max-[900px]:mb-0 max-[900px]:shrink-0 max-[900px]:pr-3">
        <Logo size="sm" />
        <span className="ml-2.5 font-mono text-[10.5px] tracking-[0.08em] text-muted-foreground uppercase max-[900px]:hidden">Console</span>
      </Link>

      {ConsoleNav.SECTIONS.map((section) => (
        <nav key={section.label} aria-label={section.label} className="contents">
          <p className="px-2.5 pt-3.5 pb-1.5 font-mono text-[10.5px] tracking-[0.1em] text-muted-foreground uppercase max-[900px]:hidden">{section.label}</p>
          {section.items.map((item) => {
            const Icon = ICONS[item.key];
            const current = ConsoleNav.isCurrent(item.href, pathname);
            const badge = item.key === "runs" ? ConsoleNav.badge(failed) : null;
            return (
              <Link
                key={item.key}
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-[10px] px-2.5 py-2 font-bold whitespace-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50 max-[900px]:shrink-0 max-[900px]:py-1.5",
                  current ? "bg-primary-soft text-primary-text" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-[18px] shrink-0" aria-hidden="true" />
                {item.label}
                {badge ? (
                  <span className="ml-auto rounded-full bg-destructive-soft px-[7px] py-px text-[11px] font-extrabold text-destructive-text">
                    {badge}
                    <span className="sr-only"> failed in the last 24 hours</span>
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>
      ))}

      <div className="mt-auto grid gap-2 border-t pt-3 max-[900px]:mt-0 max-[900px]:ml-2 max-[900px]:flex max-[900px]:shrink-0 max-[900px]:items-center max-[900px]:border-t-0 max-[900px]:pt-0">
        <div className="flex items-center gap-2.5 px-2 max-[900px]:hidden">
          <span aria-hidden="true" className="grid size-[30px] place-items-center rounded-full bg-marigold-soft text-[13px] font-extrabold text-marigold-text">
            {Initials.of(user)}
          </span>
          <div className="min-w-0">
            <b className="block truncate text-[13px]">{user?.name || user?.email}</b>
            <small className="text-xs text-muted-foreground">Staff</small>
          </div>
        </div>
        <div className="flex items-center justify-between gap-1 px-1 max-[900px]:gap-1">
          <Link href="/lessons" className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13px] font-bold whitespace-nowrap text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            <ArrowLeftIcon className="size-3.5" aria-hidden="true" /> Back to Socra
          </Link>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
