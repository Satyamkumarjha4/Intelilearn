import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { buttonVariants } from "@/components/ui/button";
import { NAV_LINKS, REGISTER_HREF, SIGN_IN_HREF } from "@/lib/landing-content";

/** The public header: the logo, the two anchors on this page, and the way in. No app navigation: nobody is signed in. */
export function LandingHeader({ onLanding = true }: { /** False on other public pages, where the anchors lead back to the landing page. */ onLanding?: boolean }) {
  return (
    <header className="mx-auto flex h-[68px] w-full max-w-[1180px] items-center gap-3.5 px-4">
      <Link href="/" aria-label="Socra home" className="rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        <Logo size="md" />
      </Link>
      <nav aria-label="On this page" className="ml-4 flex gap-0.5 max-[900px]:hidden">
        {NAV_LINKS.map(({ href, label }) => (
          <a key={href} href={onLanding ? href : `/${href}`} className="rounded-xl px-3 py-2 font-bold text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            {label}
          </a>
        ))}
      </nav>
      <div className="flex-1" />
      <Link href={SIGN_IN_HREF} className={buttonVariants({ variant: "ghost", size: "lg", className: "max-[560px]:hidden" })}>
        Sign in
      </Link>
      <Link href={REGISTER_HREF} className={buttonVariants({ size: "lg" })}>
        Get started
      </Link>
    </header>
  );
}
