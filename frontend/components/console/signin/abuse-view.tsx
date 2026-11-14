"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { type Column, DataTable } from "@/components/console/data-table";
import { ErrorState } from "@/components/console/error-state";
import { FieldRow } from "@/components/console/field-row";
import { KpiTile } from "@/components/console/kpi-tile";
import { PageHeader } from "@/components/console/page-header";
import { CardSkeleton, KpiRowSkeleton } from "@/components/console/skeletons";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { Switch } from "@/components/ui/switch";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { ConsoleFormat } from "@/lib/console-format";
import { SigninFailure } from "@/lib/console-signin/failure";
import { AbuseSummary } from "@/lib/console-signin/forms";
import { signinQueries } from "@/lib/console-signin/queries";
import type { AbuseDay, AbuseTop } from "@/lib/console-signin/types";

const dayColumns: Column<AbuseDay>[] = [
  { key: "day", header: "Day (UTC)", cell: (row) => ConsoleFormat.dayLong(row.day) },
  { key: "made", header: "Accounts made", numeric: true, cell: (row) => String(row.accounts_made) },
  { key: "codes", header: "Codes sent", numeric: true, cell: (row) => String(row.codes_sent) },
  { key: "wrong", header: "Wrong codes", numeric: true, cell: (row) => String(row.failed_checks) },
  { key: "throwaway", header: "Throwaway refused", numeric: true, cell: (row) => String(row.disposable_refused) },
  { key: "challenge", header: "Challenge failed", numeric: true, cell: (row) => String(row.captcha_failed) },
];
const topColumns = (what: string): Column<AbuseTop>[] => [
  { key: "name", header: what, cell: (row) => <span className="font-mono text-[12.5px]">{row.name}</span> },
  { key: "count", header: "Last 24 hours", numeric: true, cell: (row) => String(row.count) },
];

/** What sign-up abuse looks like (read-only), and the one lever against it: the challenge switch. It never names an email. */
export function AbuseView() {
  const queryClient = useQueryClient();
  const { data, error, isPending, refetch } = useConsoleQuery(signinQueries.abuse());
  const [busy, setBusy] = useState(false);

  const header = <PageHeader title="Sign-up abuse" description="Accounts made, codes sent and checks that failed, so a flood is easy to see. Read-only, apart from the challenge switch." />;
  if (error && !data) return <>{header}<ErrorState message="The abuse board could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !data) {
    return (
      <div aria-busy="true">
        {header}
        <KpiRowSkeleton count={4} />
        <div className="mt-4"><CardSkeleton height={200} /></div>
      </div>
    );
  }

  const totals = AbuseSummary.totals(data.days);
  const { challenge } = data;
  const toggle = async (next: boolean) => {
    setBusy(true);
    try {
      await consoleApi.setCaptcha(next);
      await queryClient.invalidateQueries({ queryKey: ["console", "abuse"] });
      toast.success(next ? "Visitors must now pass the check to sign up or ask for a code." : "The check is off.");
    } catch (failure) {
      toast.error(SigninFailure.message(failure) ?? ConsoleFailure.of(failure).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {header}
      <div className="grid grid-cols-4 gap-4 max-[1180px]:grid-cols-2 max-[560px]:grid-cols-1">
        <KpiTile data={{ label: "Accounts made", value: String(totals.accounts_made), detail: "in the last 14 days" }} />
        <KpiTile data={{ label: "Wrong codes", value: String(totals.failed_checks), detail: "in the last 14 days" }} />
        <KpiTile data={{ label: "Waiting for a code", value: String(data.waiting_signups), detail: "sign-ups not finished" }} />
        <KpiTile data={{ label: "Emails locked now", value: String(data.locked_emails), detail: "too many dead codes" }} />
      </div>

      <section aria-label="Sign-up check" className="mt-4 rounded-2xl border bg-card px-[18px] py-2 shadow-card">
        <FieldRow
          labelId="captcha-label"
          label="Ask visitors to pass a check"
          help={
            challenge.configured
              ? "Cloudflare Turnstile on the sign-up and “send a new code” screens. Off by default; every change is in the change log."
              : `Not set up: add ${challenge.missing.join(" and ")} to the environment first.`
          }
        >
          <Switch aria-labelledby="captcha-label" checked={challenge.captcha_enabled} disabled={busy || (!challenge.configured && !challenge.captcha_enabled)} onCheckedChange={(next) => void toggle(next)} />
        </FieldRow>
      </section>

      <section aria-label="Per day" className="mt-4 rounded-2xl border bg-card p-[18px] shadow-card">
        <h2 className="mb-2 font-sans text-base font-extrabold">Per day, last 14 days</h2>
        <DataTable columns={dayColumns} rows={[...data.days].reverse()} rowKey={(row) => row.day} caption="Sign-up activity per day, today first" />
      </section>

      <div className="mt-4 grid gap-4 min-[900px]:grid-cols-2">
        <section aria-label="Busiest addresses" className="rounded-2xl border bg-card p-[18px] shadow-card">
          <h2 className="mb-2 font-sans text-base font-extrabold">Busiest client addresses</h2>
          {data.top_addresses.length ? <DataTable columns={topColumns("Address")} rows={data.top_addresses} rowKey={(row) => row.name} caption="Client addresses with the most sign-up activity in the last 24 hours" /> : <p className="text-muted-foreground">Nothing in the last 24 hours.</p>}
        </section>
        <section aria-label="Busiest email domains" className="rounded-2xl border bg-card p-[18px] shadow-card">
          <h2 className="mb-2 font-sans text-base font-extrabold">Busiest email domains</h2>
          {data.top_domains.length ? <DataTable columns={topColumns("Domain")} rows={data.top_domains} rowKey={(row) => row.name} caption="Email domains with the most sign-up activity in the last 24 hours" /> : <p className="text-muted-foreground">Nothing in the last 24 hours.</p>}
        </section>
      </div>
    </div>
  );
}
