import { AlertTriangleIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

type Props = { title?: string; message?: string; onRetry?: () => void };

/** A request failed (the console answers 404 for "not yours", which never gets here). */
export function ErrorState({ title = "Could not load this", message = "The server did not answer as expected.", onRetry }: Props) {
  return (
    <div role="alert" className="grid justify-items-center gap-2 rounded-2xl border border-destructive/30 bg-destructive-soft px-4 py-8 text-center text-destructive-text">
      <AlertTriangleIcon className="size-6" aria-hidden="true" />
      <p className="font-heading text-base font-semibold">{title}</p>
      <p className="max-w-md">{message}</p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
