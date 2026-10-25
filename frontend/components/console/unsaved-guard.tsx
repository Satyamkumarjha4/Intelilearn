"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { UnsavedGuard } from "@/lib/unsaved-guard";

/**
 * Warns before a page with unsaved edits is left. A click on a link to another page opens a confirmation (the capture
 * phase gets there before the link's own handler); closing or reloading the tab gets the browser's own warning. The
 * browser's Back button is not caught: Next.js gives a page no hook for it.
 */
export function UnsavedChangesGuard({ dirty }: { dirty: boolean }) {
  const router = useRouter();
  const [destination, setDestination] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) return;
    const onClick = (event: MouseEvent) => {
      const anchor = event.target instanceof Element ? event.target.closest("a") : null;
      const next = UnsavedGuard.destination(
        {
          href: anchor?.href ?? null,
          target: anchor?.target ?? "",
          download: anchor?.hasAttribute("download") ?? false,
          button: event.button,
          modified: event.ctrlKey || event.metaKey || event.shiftKey || event.altKey,
          handled: event.defaultPrevented,
        },
        { origin: window.location.origin, pathname: window.location.pathname },
      );
      if (next === null) return;
      event.preventDefault();
      event.stopPropagation();
      setDestination(next);
    };
    const onLeave = (event: BeforeUnloadEvent) => event.preventDefault();
    document.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onLeave);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onLeave);
    };
  }, [dirty]);

  return (
    <ConfirmDialog
      open={destination !== null}
      onOpenChange={(open) => !open && setDestination(null)}
      title="Leave without saving?"
      description="You have unsaved changes on this page. If you leave now, they are lost."
      confirmLabel="Leave page"
      cancelLabel="Stay and keep editing"
      onConfirm={() => {
        if (destination) router.push(destination);
      }}
    />
  );
}
