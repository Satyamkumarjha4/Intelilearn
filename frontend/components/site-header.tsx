"use client";

import { GraduationCapIcon, LogOutIcon, UserIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { useAuth } from "@/components/auth-provider";
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

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}

export function SiteHeader() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  const signOut = async () => {
    try {
      await logout();
      toast.success("Signed out");
    } catch {
      toast.error("Could not sign out. Please try again.");
    }
  };

  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <GraduationCapIcon className="size-5" />
          Lesson Crafter
        </Link>

        {loading ? null : user ? (
          <DropdownMenu>
            <DropdownMenuTrigger
              className={buttonVariants({ variant: "ghost", className: "gap-2" })}
              aria-label="Account menu"
            >
              <span className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                {initials(user.name) || "?"}
              </span>
              <span className="hidden max-w-40 truncate sm:inline">{user.name}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuGroup>
                <DropdownMenuLabel className="truncate font-normal text-muted-foreground">{user.email}</DropdownMenuLabel>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => router.push("/profile")}>
                <UserIcon /> Profile
              </DropdownMenuItem>
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
    </header>
  );
}
