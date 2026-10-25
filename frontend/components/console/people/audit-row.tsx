"use client";

import { ChevronDownIcon } from "lucide-react";
import { useId, useState } from "react";

import { AuditDiff, AuditText } from "@/lib/console-audit";
import { RunText } from "@/lib/run-text";
import type { AuditEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = { entry: AuditEntry; now: Date; modelNames: ReadonlyMap<string, string> };

/** One change: who, a sentence with its targets in code, when (exact time on hover), and a before → after diff on request. */
export function AuditRow({ entry, now, modelNames }: Props) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const actor = AuditText.actor(entry);
  const diff = AuditDiff.rows(entry);

  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2.5 gap-y-1 border-b border-border/60 py-2.5 text-[13.5px] last:border-b-0">
      <span aria-hidden="true" title={actor.title || actor.name} className="grid size-6 place-items-center rounded-full bg-marigold-soft text-[11px] font-extrabold text-marigold-text">
        {actor.initial}
      </span>
      <div className="min-w-0">
        <p className="break-words">
          {AuditText.sentence(entry, modelNames).map((part, index) =>
            part.code ? (
              <code key={index} className="rounded-[5px] bg-muted px-1.5 py-px font-mono text-xs break-words">
                {part.text}
              </code>
            ) : (
              <span key={index}>{part.text}</span>
            ),
          )}
          <span className="text-muted-foreground"> · by {actor.name}</span>
        </p>
        {diff.length > 0 ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panel}
            onClick={() => setOpen((on) => !on)}
            className="mt-0.5 inline-flex items-center gap-1 rounded text-[12.5px] font-extrabold text-primary-text outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <ChevronDownIcon className={cn("size-3.5 motion-safe:transition-transform", open && "rotate-180")} aria-hidden="true" />
            {open ? "Hide changes" : `Show changes (${diff.length})`}
          </button>
        ) : null}
      </div>
      <time dateTime={entry.created_at} title={RunText.exact(entry.created_at)} className="font-mono text-[11.5px] whitespace-nowrap text-muted-foreground">
        {RunText.ago(entry.created_at, now)}
      </time>

      {open ? (
        <div id={panel} className="col-span-2 col-start-2 col-end-4 mt-1 overflow-auto rounded-xl bg-muted/50">
          <table className="w-full border-collapse text-[12.5px]">
            <caption className="sr-only">What changed, before and after</caption>
            <thead>
              <tr className="text-left text-[11px] tracking-wide text-muted-foreground uppercase">
                <th scope="col" className="px-3 py-1.5 font-extrabold">Field</th>
                <th scope="col" className="px-3 py-1.5 font-extrabold">Before</th>
                <th scope="col" className="px-3 py-1.5 font-extrabold">After</th>
              </tr>
            </thead>
            <tbody>
              {diff.map((row) => (
                <tr key={row.field} className="border-t border-border/60 align-top">
                  <th scope="row" className="px-3 py-1.5 text-left font-bold whitespace-nowrap">{row.field}</th>
                  <td className="px-3 py-1.5 font-mono break-all text-muted-foreground">{row.before}</td>
                  <td className="bg-primary-soft/50 px-3 py-1.5 font-mono break-all text-primary-text">{row.after}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </li>
  );
}
