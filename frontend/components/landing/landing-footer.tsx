import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { FOOTER_COLUMNS, SUPPORT_EMAIL } from "@/lib/landing-content";

/** The public footer: what Socra is, three columns of links to pages that exist, and the one support address. */
export function LandingFooter() {
  return (
    <footer className="border-t border-border bg-card">
      <div className="mx-auto flex w-full max-w-[1200px] flex-wrap justify-between gap-10 px-4 py-12 sm:px-6">
        <div className="flex min-w-0 flex-1 basis-64 flex-col gap-3">
          <Logo size="md" />
          <p className="text-base text-muted-foreground">Lessons that start from what you already know.</p>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-14 gap-y-8 text-base">
          {FOOTER_COLUMNS.map((column) => (
            <div key={column.title} className="flex flex-col gap-2.5">
              <span className="font-extrabold">{column.title}</span>
              {column.links.map((link) => {
                const className = "rounded-md text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-3 focus-visible:ring-ring/50";
                return link.href.startsWith("mailto:") ? (
                  <a key={link.label} href={link.href} className={className}>
                    {link.label}
                  </a>
                ) : (
                  <Link key={link.label} href={link.href} className={className}>
                    {link.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </div>
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-8 text-[15px] text-muted-foreground sm:px-6">
        © 2026 Socra · Support:{" "}
        <a href={`mailto:${SUPPORT_EMAIL}`} className="font-bold text-primary-text underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          {SUPPORT_EMAIL}
        </a>
      </div>
    </footer>
  );
}
