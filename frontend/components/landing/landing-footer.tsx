import Link from "next/link";

import { FOOTER_LINKS } from "@/lib/landing-content";

/** The public footer: Privacy, Terms and Contact. */
export function LandingFooter() {
  return (
    <footer className="mx-auto w-full max-w-[1180px] px-4">
      <div className="flex flex-wrap justify-between gap-3 border-t-[1.5px] border-border pt-5 pb-8 text-sm font-semibold text-muted-foreground">
        <span>© 2026 Socra</span>
        <nav aria-label="Footer" className="flex gap-4">
          {FOOTER_LINKS.map(({ href, label }) => (
            <Link key={href} href={href} className="rounded-md underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
