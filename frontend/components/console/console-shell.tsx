"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { notFound, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ConsoleSidebar } from "@/components/console/console-sidebar";
import { PageSkeleton } from "@/components/console/skeletons";
import { ConsoleGate } from "@/lib/console-gate";
import { ConsoleQueryClient } from "@/lib/console-queries";

/**
 * Everything under /console: the cache for its queries (TanStack Query is the console's only), the check of who is
 * looking, and the frame (menu and page). The queries start only once staff is confirmed, so a learner who types the
 * address makes no console request and sees the ordinary not-found page.
 */
export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const [client] = useState(ConsoleQueryClient.create);
  return (
    <QueryClientProvider client={client}>
      <AccessGate>
        <div className="grid min-h-screen flex-1 grid-cols-[232px_minmax(0,1fr)] text-[14px] max-[900px]:grid-cols-1">
          <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-20 focus:rounded-lg focus:bg-card focus:px-3 focus:py-2 focus:font-bold focus:shadow-card">
            Skip to content
          </a>
          <ConsoleSidebar />
          <main id="main" tabIndex={-1} className="min-w-0 px-7 pt-6 pb-12 outline-none max-[900px]:px-4 max-[900px]:pt-[18px]">
            {children}
          </main>
        </div>
      </AccessGate>
    </QueryClientProvider>
  );
}

function AccessGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, loading } = useAuth();
  const access = ConsoleGate.decide({ loading, user });

  useEffect(() => {
    // The proxy already sends visitors without a session; this covers a stale session marker.
    if (access === "signed-out") router.replace(ConsoleGate.signInHref(window.location.pathname, window.location.search));
  }, [access, router]);

  if (access === "denied") notFound();
  if (access !== "allowed") {
    return (
      <div className="px-7 pt-6">
        <PageSkeleton />
      </div>
    );
  }
  return children;
}
