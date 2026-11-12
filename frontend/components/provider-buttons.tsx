"use client";

import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { SignInProviders, type SignInProvider } from "@/lib/sign-in-providers";
import { cn } from "@/lib/utils";

/**
 * "Continue with Google" (and any other provider that is on). It draws nothing until the server says which providers work, and
 * nothing at all when none does or the list cannot be read, so the email form is never pushed around by a button that is not
 * there. Each button is a plain link: signing in with a provider is a whole-page trip to the provider and back.
 */
export function ProviderButtons({ next, placement = "above" }: { next: string; placement?: "above" | "below" }) {
  const [providers, setProviders] = useState<SignInProvider[]>([]);

  useEffect(() => {
    let active = true;
    new SignInProviders().load().then((list) => {
      if (active) setProviders(list);
    });
    return () => {
      active = false;
    };
  }, []);

  if (providers.length === 0) return null;
  const divider = (
    <div className="flex items-center gap-3 text-sm text-muted-foreground" aria-hidden="true">
      <span className="h-px flex-1 bg-border" />
      or
      <span className="h-px flex-1 bg-border" />
    </div>
  );

  return (
    <div className="flex flex-col gap-4">
      {placement === "below" && divider}
      <div className="flex flex-col gap-3">
        {providers.map((provider) => (
          <a
            key={provider.key}
            href={SignInProviders.startHref(provider, next)}
            className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 w-full")}
          >
            {SignInProviders.buttonLabel(provider)}
          </a>
        ))}
      </div>
      {placement === "above" && divider}
    </div>
  );
}
