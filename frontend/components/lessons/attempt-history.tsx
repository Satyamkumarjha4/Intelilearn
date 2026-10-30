"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AttemptChart, AttemptHistoryView } from "@/lib/attempt-history";
import { DateText } from "@/lib/format";
import type { AttemptHistory as History } from "@/lib/types";
import { cn } from "@/lib/utils";

const WIDTH = 240;
const HEIGHT = 72;

type Props = {
  history: History;
  /** The attempt whose answers are on show. */
  selectedId: string;
  onSelect: (attemptId: string) => void;
};

/** Every try at the test: a small bar chart of the scores, then each attempt with its score, how it compares with the
 *  last one and with the best, and how long it took. Choosing one shows its answers. */
export function AttemptHistory({ history, selectedId, onSelect }: Props) {
  const rows = AttemptHistoryView.rows(history);
  const bars = AttemptChart.bars(history.trend.series, WIDTH, HEIGHT, 2, history.trend.best_attempt_no);
  const summary = history.trend.series.map((p) => `${p.percent}%`).join(", ");
  return (
    <section aria-labelledby="history-heading" className="flex flex-col gap-3">
      <h2 id="history-heading" className="font-heading text-xl font-semibold">Your tries</h2>
      <Card>
        <CardContent className="flex flex-col gap-4">
          {bars.length > 1 && (
            <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-20 w-full max-w-sm" role="img" aria-label={`Your scores, oldest first: ${summary}`}>
              {bars.map((bar) => (
                <path key={bar.attemptNo} d={bar.path} className={bar.best ? "fill-success" : "fill-primary"}>
                  <title>{bar.label}</title>
                </path>
              ))}
            </svg>
          )}
          <ol className="flex flex-col divide-y divide-border">
            {rows.map((row) => (
              <li key={row.attemptNo} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5">
                <div className="flex min-w-0 flex-col gap-0.5">
                  <p className="flex flex-wrap items-center gap-2 font-semibold">
                    {row.title}
                    {row.best && <Badge variant="success">Best</Badge>}
                    {row.state && <Badge variant="secondary">{row.state}</Badge>}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {[row.submittedAt ? DateText.day(row.submittedAt) : "", row.duration && `took ${row.duration}`].filter(Boolean).join(" · ")}
                  </p>
                  {row.changes.length > 0 && <p className="text-sm text-muted-foreground">{row.changes.join(" · ")}</p>}
                </div>
                <div className="flex items-center gap-3">
                  {row.percentText && (
                    <p className="text-right">
                      <span className="font-heading text-xl font-semibold tabular-nums">{row.percentText}</span>
                      <span className="block font-mono text-xs text-muted-foreground">{row.marks}</span>
                    </p>
                  )}
                  {row.percent !== null && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={`See the answers of ${row.title}`}
                      aria-pressed={selectedId === history.attempts.find((a) => a.attempt_no === row.attemptNo)?.id}
                      className={cn(selectedId === history.attempts.find((a) => a.attempt_no === row.attemptNo)?.id && "pointer-events-none opacity-60")}
                      onClick={() => onSelect(history.attempts.find((a) => a.attempt_no === row.attemptNo)!.id)}
                    >
                      See answers
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>
    </section>
  );
}
