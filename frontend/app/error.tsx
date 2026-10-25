"use client";

import { CloudAlertIcon } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { StatusCard } from "@/components/status-card";
import { Button, buttonVariants } from "@/components/ui/button";

export default function ErrorPage({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-4 py-10">
      <StatusCard
        icon={CloudAlertIcon}
        tone="destructive"
        title="Something went wrong"
        actions={
          <>
            <Button onClick={() => retry()}>Try again</Button>
            <Link href="/lessons" className={buttonVariants({ variant: "outline" })}>
              Back to my lessons
            </Link>
          </>
        }
      >
        <p>That was our mistake, not yours. Trying again usually helps.</p>
      </StatusCard>
    </main>
  );
}
