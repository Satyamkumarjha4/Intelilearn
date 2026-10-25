"use client";

import { ExternalLinkIcon } from "lucide-react";

import { type Column, DataTable } from "@/components/console/data-table";
import { StatusPill } from "@/components/console/status-pill";
import { ConsoleFormat } from "@/lib/console-format";
import { AdminLinks, LearnerText } from "@/lib/console-people";
import type { ConsoleLearner } from "@/lib/types";

// Inlined at build time, so it has to be read exactly like this.
const ADMIN_URL = process.env.NEXT_PUBLIC_DJANGO_ADMIN_URL;

function columns(now: Date): Column<ConsoleLearner>[] {
  return [
    {
      key: "learner",
      header: "Learner",
      cell: (row) => (
        <div className="min-w-0">
          <span className={row.name.trim() ? "font-extrabold" : "font-semibold text-muted-foreground"}>{LearnerText.displayName(row)}</span>
          {row.is_staff ? <span className="ml-2 rounded-md bg-primary-soft px-1.5 py-px text-[11px] font-extrabold text-primary-text">Staff</span> : null}
          <span className="block max-w-64 truncate text-xs font-semibold text-muted-foreground" title={row.email}>
            {row.email}
          </span>
        </div>
      ),
    },
    { key: "studies", header: "Studies", cell: (row) => LearnerText.studies(row) },
    { key: "goal", header: "Goal", cell: (row) => LearnerText.goal(row) },
    { key: "language", header: "Language", cell: (row) => <span lang={row.preferred_language || undefined}>{LearnerText.language(row.preferred_language)}</span> },
    { key: "lessons", header: "Lessons", numeric: true, cell: (row) => ConsoleFormat.count(row.lessons_count) },
    {
      key: "active",
      header: "Last active",
      cell: (row) => {
        const { text, title } = LearnerText.lastActive(row.last_active_at, now);
        return <span title={title}>{text}</span>;
      },
    },
    {
      key: "onboarding",
      header: "Onboarding",
      cell: (row) => {
        const { label, tone } = LearnerText.onboarding(row);
        return <StatusPill tone={tone}>{label}</StatusPill>;
      },
    },
    {
      key: "admin",
      header: "Account",
      cell: (row) => {
        const href = AdminLinks.userChange(ADMIN_URL, row.id);
        return href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open ${LearnerText.displayName(row)} (${row.email}) in Django admin, opens in a new tab`}
            className="inline-flex items-center gap-1 rounded text-[12.5px] font-extrabold whitespace-nowrap text-primary-text outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Open in Django admin <ExternalLinkIcon className="size-3" aria-hidden="true" />
          </a>
        ) : null;
      },
    },
  ];
}

/** Read-only: the list is in the order the API gives (newest member first), so no column sorts only the loaded part. */
export function LearnersTable({ rows, now }: { rows: readonly ConsoleLearner[]; now: Date }) {
  return <DataTable columns={columns(now)} rows={rows} rowKey={(row) => row.id} caption="Learners, newest first" />;
}
