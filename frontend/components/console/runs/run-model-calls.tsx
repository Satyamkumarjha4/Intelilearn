import { RunStatusPill } from "@/components/console/runs/run-status-pill";
import { RunText } from "@/lib/run-text";
import type { RunModelCall } from "@/lib/types";

/** The run's latest model calls: step, model, which fallback it was, how long it took and how it went. */
export function RunModelCalls({ calls }: { calls: RunModelCall[] }) {
  if (calls.length === 0) return <p className="text-sm text-muted-foreground">No model calls yet.</p>;
  return (
    <ul className="grid gap-1.5">
      {calls.map((call) => {
        const result = RunText.callResult(call);
        return (
          <li
            key={call.id}
            className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2.5 rounded-lg bg-muted px-2 py-1.5 text-[12.5px]"
          >
            <span className="truncate font-mono" title={call.error || undefined}>
              {call.node} · {call.model}
              {call.fallback_index > 0 && <span className="text-muted-foreground"> fallback {call.fallback_index}</span>}
              {call.tool_calls > 0 && <span className="text-muted-foreground"> · {call.tool_calls} tool calls</span>}
            </span>
            <span className="font-mono text-muted-foreground">{RunText.duration(call.latency_s)}</span>
            <RunStatusPill {...result} />
          </li>
        );
      })}
    </ul>
  );
}
