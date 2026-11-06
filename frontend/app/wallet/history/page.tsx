"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { LoadFailure, PageFrame } from "@/components/credits/page-frame";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { creditsApi } from "@/lib/credits/credits-api";
import { HistoryWords } from "@/lib/credits/history-words";
import type { Transaction } from "@/lib/credits/types";
import { LessonsApi } from "@/lib/lessons-api";
import { cn } from "@/lib/utils";

export default function HistoryPage() {
  const [rows, setRows] = useState<Transaction[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [more, setMore] = useState(false);

  useEffect(() => {
    let active = true;
    creditsApi
      .transactions()
      .then((page) => {
        if (!active) return;
        setRows(page.results);
        setNext(LessonsApi.cursorOf(page.next));
      })
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "We couldn't load your history."));
    return () => {
      active = false;
    };
  }, []);

  const showMore = async () => {
    setMore(true);
    try {
      const page = await creditsApi.transactions(next);
      setRows((current) => [...(current ?? []), ...page.results]);
      setNext(LessonsApi.cursorOf(page.next));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't load more.");
    } finally {
      setMore(false);
    }
  };

  const days = rows ? HistoryWords.byDay(rows) : [];

  return (
    <PageFrame eyebrow="Your credits" title="History">
      <Link href="/wallet" className={buttonVariants({ variant: "ghost", className: "w-fit gap-1.5" })}>
        <ArrowLeftIcon aria-hidden="true" /> Back to your credits
      </Link>
      {error && <LoadFailure message={error} />}
      {!rows && !error && <Skeleton className="h-48 rounded-[22px]" aria-busy="true" aria-label="Loading your history" />}
      {rows?.length === 0 && <p className="rounded-xl border-2 border-dashed p-4 text-center text-muted-foreground">{HistoryWords.EMPTY}</p>}

      {days.map((day) => (
        <section key={day.key} aria-label={day.heading} className="flex flex-col gap-2">
          <h2 className="font-heading text-lg font-semibold">{day.heading}</h2>
          <Card size="sm">
            <ul className="divide-y" data-testid="history-rows">
              {day.rows.map((row) => {
                const tone = HistoryWords.tone(row.amount);
                return (
                  <li key={row.id} className="flex items-center justify-between gap-3 px-3 py-2" data-testid="history-row">
                    <div className="min-w-0">
                      <p className="break-words">{row.text}</p>
                      <p className="font-mono text-xs text-muted-foreground">{HistoryWords.time(row.created_at)}</p>
                    </div>
                    <p
                      className={cn("shrink-0 font-mono text-base font-bold tabular-nums", tone === "gain" && "text-success-text", tone === "spend" && "text-foreground")}
                      aria-label={`${row.amount > 0 ? "plus" : row.amount < 0 ? "minus" : ""} ${Math.abs(row.amount)}`.trim()}
                    >
                      {HistoryWords.amount(row.amount)}
                    </p>
                  </li>
                );
              })}
            </ul>
          </Card>
        </section>
      ))}

      {next && (
        <Button variant="outline" className="self-center" disabled={more} onClick={() => void showMore()}>
          {more ? "Loading…" : "Show older"}
        </Button>
      )}
    </PageFrame>
  );
}
