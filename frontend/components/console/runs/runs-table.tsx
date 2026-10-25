import { RunStatusPill } from "@/components/console/runs/run-status-pill";
import { RunText } from "@/lib/run-text";
import type { RunRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { rows: RunRow[]; selected: string | null; onOpen: (id: string) => void; now: Date };

const HEAD = "px-3 py-2 text-left text-[11.5px] font-extrabold tracking-wider whitespace-nowrap text-muted-foreground uppercase";

/**
 * One row per run. A row takes focus and opens its detail on Enter (or Space) as well as on a click. Below the
 * medium width the job, time, calls, cost and start fold into a line under the topic, so the table never scrolls
 * sideways.
 */
export function RunsTable({ rows, selected, onOpen, now }: Props) {
  return (
    <table className="w-full border-collapse text-[13.5px]">
      <caption className="sr-only">Lesson runs, newest first. Press Enter on a row to open it.</caption>
      <thead>
        <tr className="border-b-[1.5px]">
          <th scope="col" className={HEAD}>Lesson</th>
          <th scope="col" className={cn(HEAD, "hidden md:table-cell")}>Job</th>
          <th scope="col" className={HEAD}>Status</th>
          <th scope="col" className={cn(HEAD, "hidden text-right md:table-cell")}>Time</th>
          <th scope="col" className={cn(HEAD, "hidden text-right md:table-cell")}>Calls</th>
          <th scope="col" className={cn(HEAD, "hidden text-right md:table-cell")}>Cost</th>
          <th scope="col" className={cn(HEAD, "hidden md:table-cell")}>Started</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((run) => {
          const status = RunText.status(run.status);
          const open = () => onOpen(run.id);
          const started = RunText.ago(run.created_at, now);
          return (
            <tr
              key={run.id}
              tabIndex={0}
              aria-current={run.id === selected ? "true" : undefined}
              onClick={open}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  open();
                }
              }}
              className={cn(
                "cursor-pointer border-b outline-none last:border-b-0 hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
                run.id === selected && "bg-primary-soft hover:bg-primary-soft",
              )}
            >
              <td className="max-w-0 px-3 py-2.5 md:max-w-64">
                <span className="block truncate font-extrabold">{run.topic}</span>
                <span className="block truncate text-xs font-semibold text-muted-foreground">
                  {run.learner_name} · <span className="font-mono">{RunText.shortId(run.id)}</span>
                </span>
                <span className="block text-xs font-semibold text-muted-foreground md:hidden">
                  {RunText.job(run.graph)} · {RunText.duration(run.duration_s)} · {RunText.cost(run.cost)} · {started}
                </span>
              </td>
              <td className="hidden px-3 py-2.5 md:table-cell">{RunText.job(run.graph)}</td>
              <td className="px-3 py-2.5">
                <RunStatusPill {...status} />
                <span className="mt-0.5 block text-xs font-semibold text-muted-foreground">{RunText.stage(run.stage)}</span>
              </td>
              <td className="hidden px-3 py-2.5 text-right font-mono text-[12.5px] whitespace-nowrap md:table-cell">{RunText.duration(run.duration_s)}</td>
              <td className="hidden px-3 py-2.5 text-right font-mono text-[12.5px] md:table-cell">{run.calls}</td>
              <td className="hidden px-3 py-2.5 text-right font-mono text-[12.5px] whitespace-nowrap md:table-cell">{RunText.cost(run.cost)}</td>
              <td className="hidden px-3 py-2.5 whitespace-nowrap text-muted-foreground md:table-cell">
                <time dateTime={run.created_at} title={RunText.exact(run.created_at)}>
                  {started}
                </time>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
