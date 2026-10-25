"use client";

import { CloudAlertIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { StatusCard } from "@/components/status-card";
import { Button, buttonVariants } from "@/components/ui/button";
import { PlainError } from "@/lib/plain-notes";

/** A lesson that stopped: what happened in plain words, and the two things to do about it. */
export function FailedCard({ error, onRetry }: { error: string; onRetry: () => void | Promise<void> }) {
  const [retrying, setRetrying] = useState(false);
  const retry = async () => {
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      setRetrying(false);
    }
  };
  return (
    <StatusCard
      icon={CloudAlertIcon}
      tone="destructive"
      heading="h2"
      title="We couldn't finish building this"
      actions={
        <>
          <Button onClick={retry} disabled={retrying}>
            {retrying ? "Retrying…" : "Retry"}
          </Button>
          <Link href="/lessons" className={buttonVariants({ variant: "outline" })}>
            Back to my lessons
          </Link>
        </>
      }
    >
      <p>{PlainError.of(error)}</p>
      <p className="text-sm">Nothing is lost. Retry carries on from the last saved step.</p>
    </StatusCard>
  );
}
