"use client";

import { BookOpenIcon, LayoutDashboardIcon, LogOutIcon, UserIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConsoleGate } from "@/lib/console-gate";
import { Initials } from "@/lib/initials";

export function SiteHeader() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const signOut = async () => {
    try {
      await logout();
      toast.success("Signed out");
    } catch {
      toast.error("Could not sign out. Please try again.");
    }
  };

  // The landing page has its own public header; the app's only starts once someone is signed in.
  // The same goes for the sign-in page (it has its own brand panel), the public legal pages and the setup (a focused page, no app navigation).
  // The staff console has its own menu and frame.
  if (["/", "/auth", "/privacy", "/terms", "/contact", "/onboarding"].includes(pathname) || pathname === "/console" || pathname.startsWith("/console/")) return null;

  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between px-4">
        <Link href="/" aria-label="Socra home" className="rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <Logo size="sm" />
        </Link>

        <div className="flex items-center gap-1">
          <ThemeToggle />
          {loading ? null : user ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                className={buttonVariants({ variant: "ghost", className: "gap-2" })}
                aria-label="Account menu"
              >
                <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                  {Initials.of(user)}
                </span>
                <span className="hidden max-w-40 truncate sm:inline">{user.name}</span>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="truncate font-normal text-muted-foreground">{user.email}</DropdownMenuLabel>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => router.push("/lessons")}>
                  <BookOpenIcon /> Your lessons
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => router.push("/profile")}>
                  <UserIcon /> Profile
                </DropdownMenuItem>
                {ConsoleGate.offeredTo(user) ? (
                  <DropdownMenuItem onClick={() => router.push("/console")}>
                    <LayoutDashboardIcon /> Console
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem onClick={signOut}>
                  <LogOutIcon /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <div className="flex gap-2">
              <Link href="/auth" className={buttonVariants({ variant: "ghost" })}>
                Sign in
              </Link>
              <Link href="/auth?mode=register" className={buttonVariants()}>
                Get started
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
