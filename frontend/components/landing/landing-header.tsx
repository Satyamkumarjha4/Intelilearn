import { cookies } from "next/headers";
import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { APP_HREF, NAV_LINKS, REGISTER_HREF, SESSION_COOKIE, SIGN_IN_HREF } from "@/lib/landing-content";

/**
 * The public header: the logo, the sections of the page, and the way in. Someone who is signed in sees "Go to my lessons"
 * instead of Sign in and Start free; that is read from the session marker cookie on the server, so there is no flash.
 */
export async function LandingHeader({ onLanding = true }: { /** False on other public pages, where the anchors lead back to the landing page. */ onLanding?: boolean }) {
  const signedIn = (await cookies()).has(SESSION_COOKIE);
  return (
    <header className="border-b border-border bg-background">
      <div className="mx-auto flex w-full max-w-[1200px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/" aria-label="Socra home" className="rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <Logo size="md" />
        </Link>
        <nav aria-label="On this page" className="ml-4 flex gap-1 max-[900px]:hidden">
          {NAV_LINKS.map(({ href, label }) => (
            <a key={href} href={onLanding ? href : `/${href}`} className="rounded-xl px-3 py-2 font-bold text-foreground outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50">
              {label}
            </a>
          ))}
        </nav>
        <div className="flex-1" />
        <ThemeToggle />
        {signedIn ? (
          <Link href={APP_HREF} className={buttonVariants({ size: "xl" })}>
            Go to my lessons
          </Link>
        ) : (
          <>
            <Link href={SIGN_IN_HREF} className={buttonVariants({ variant: "ghost", size: "xl", className: "max-[560px]:hidden" })}>
              Sign in
            </Link>
            <Link href={REGISTER_HREF} className={buttonVariants({ size: "xl" })}>
              Start free
            </Link>
          </>
        )}
      </div>
    </header>
  );
}
