"use client";

import { CloudAlertIcon } from "lucide-react";
import { Fredoka, Nunito } from "next/font/google";
import { useEffect } from "react";

import { StatusCard } from "@/components/status-card";
import { Button } from "@/components/ui/button";
import "./globals.css";

const fredoka = Fredoka({ variable: "--font-fredoka", subsets: ["latin"], weight: ["500", "600"] });
const nunito = Nunito({ variable: "--font-nunito", subsets: ["latin"], weight: ["400", "600", "700", "800"] });

/** The last resort: the root layout itself failed, so this replaces it (and has to bring its own <html> and <body>). */
export default function GlobalError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en" className={`${fredoka.variable} ${nunito.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col justify-center bg-background px-4 py-10 font-sans text-foreground">
        <StatusCard
          icon={CloudAlertIcon}
          tone="destructive"
          title="Something went wrong"
          actions={<Button onClick={() => retry()}>Try again</Button>}
        >
          <p>That was our mistake, not yours. Trying again usually helps.</p>
        </StatusCard>
      </body>
    </html>
  );
}
