"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/console/error-state";

/** A console page crashed while drawing: the shell around it (sidebar, header) stays, and the page can be tried again. */
export default function ConsoleError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return <ErrorState title="This page could not be drawn" message="Something went wrong while showing it. Try again, or open another page from the menu." onRetry={() => retry()} />;
}
