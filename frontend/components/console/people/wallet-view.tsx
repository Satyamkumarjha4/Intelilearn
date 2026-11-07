"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { type Column, DataTable } from "@/components/console/data-table";
import { ErrorState } from "@/components/console/error-state";
import { FieldRow, StackedField, TextBox } from "@/components/console/field-row";
import { KpiTile } from "@/components/console/kpi-tile";
import { PageHeader } from "@/components/console/page-header";
import { CardSkeleton, KpiRowSkeleton } from "@/components/console/skeletons";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { consoleApi } from "@/lib/console-api";
import { AdjustForm } from "@/lib/console-credits/forms";
import { creditQueries } from "@/lib/console-credits/queries";
import type { LedgerRow, WalletBucket, WalletPanel } from "@/lib/console-credits/types";
import { ConsoleFailure } from "@/lib/console-failure";
import { ConsoleFormat } from "@/lib/console-format";

const SOURCES: Record<string, string> = {
  signup: "Signup",
  daily: "Daily study",
  weekly_streak: "Weekly streak",
  monthly_streak: "Monthly streak",
  purchase: "Bought",
  subscription: "Plan",
  admin_grant: "Given by staff",
  refund: "Given back after a failure",
};

const bucketColumns: Column<WalletBucket>[] = [
  { key: "source", header: "Kind", cell: (row) => SOURCES[row.source] ?? row.source },
  { key: "remaining", header: "Left", numeric: true, cell: (row) => `${row.remaining} of ${row.granted}` },
  { key: "expires", header: "Runs out", cell: (row) => (row.expires_at ? `${ConsoleFormat.dayLong(row.expires_at)}${row.lapsed ? " (lapsed)" : ""}` : "Never") },
];
const ledgerColumns: Column<LedgerRow>[] = [
  { key: "when", header: "When", cell: (row) => ConsoleFormat.dayLong(row.created_at) },
  { key: "type", header: "What", cell: (row) => <span className="font-mono text-[12.5px]">{row.type}{row.action ? ` · ${row.action}` : ""}</span> },
  { key: "amount", header: "Credits", numeric: true, cell: (row) => (row.amount > 0 ? `+${row.amount}` : String(row.amount)) },
  { key: "after", header: "Balance", numeric: true, cell: (row) => String(row.balance_after) },
  { key: "reason", header: "Reason", cell: (row) => row.reason || "" },
];

/** One learner's wallet for support: the balance, what it is made of, the last movements, a give-or-take form that needs a reason, and the exempt switch. */
export function WalletView({ learnerId }: { learnerId: string }) {
  const queryClient = useQueryClient();
  const { data, error, isPending, refetch } = useConsoleQuery(creditQueries.wallet(learnerId));
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [token, setToken] = useState(() => crypto.randomUUID());
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);

  const header = (
    <>
      <Link href="/console/learners" className="mb-2 inline-flex items-center gap-1 text-[13px] font-extrabold text-primary-text hover:underline">
        <ArrowLeftIcon className="size-3.5" aria-hidden="true" /> Learners
      </Link>
      <PageHeader title={data ? (data.learner.name.trim() || data.learner.email) : "Wallet"} description={data ? data.learner.email : undefined} />
    </>
  );
  if (error && !data) return <>{header}<ErrorState message="This wallet could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !data) {
    return (
      <div aria-busy="true">
        {header}
        <KpiRowSkeleton count={3} />
        <div className="mt-4"><CardSkeleton height={160} /></div>
      </div>
    );
  }

  const put = (next: WalletPanel) => queryClient.setQueryData(creditQueries.wallet(learnerId).queryKey, next);
  const problems = AdjustForm.errors(amount, reason);
  const invalid = Object.keys(problems).length > 0;

  const adjust = async () => {
    setTouched(true);
    if (invalid) return;
    setBusy(true);
    try {
      put(await consoleApi.adjustWallet(learnerId, { amount: AdjustForm.amount(amount)!, reason: reason.trim(), token }));
      toast.success("Done. The movement is on the ledger and in the change log.");
      setAmount("");
      setReason("");
      setTouched(false);
      setToken(crypto.randomUUID());
    } catch (failure) {
      toast.error(ConsoleFailure.of(failure).lines({ amount: "Credits", reason: "Reason" }).join(" "));
    } finally {
      setBusy(false);
    }
  };
  const exempt = async (next: boolean) => {
    setBusy(true);
    try {
      put(await consoleApi.setExempt(learnerId, next));
      toast.success(next ? "This learner's work now costs nothing." : "This learner pays for their work again.");
    } catch (failure) {
      toast.error(ConsoleFailure.of(failure).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {header}
      <div className="grid grid-cols-3 gap-4 max-[900px]:grid-cols-1">
        <KpiTile data={{ label: "Can spend now", value: String(data.balance), detail: "credits that have not run out" }} />
        <KpiTile data={{ label: "Set aside", value: String(data.reserved), detail: "for work that has not finished" }} />
        <KpiTile data={{ label: "Pays for work", value: data.credits_exempt ? "No" : "Yes", detail: data.credits_exempt ? "exempt: work is recorded at 0" : "being staff does not exempt anyone", small: true }} />
      </div>

      <div className="mt-4 grid items-start gap-4 min-[1000px]:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 gap-4">
          <section aria-label="Live credits" className="rounded-2xl border bg-card p-[18px] shadow-card">
            <h2 className="mb-2 font-sans text-base font-extrabold">Live credits</h2>
            {data.buckets.length ? <DataTable columns={bucketColumns} rows={data.buckets} rowKey={(row) => row.id} caption="Live credits, soonest to run out first" /> : <p className="text-muted-foreground">No credits.</p>}
          </section>
          <section aria-label="Recent movements" className="rounded-2xl border bg-card p-[18px] shadow-card">
            <h2 className="mb-2 font-sans text-base font-extrabold">Recent movements</h2>
            {data.transactions.length ? <DataTable columns={ledgerColumns} rows={data.transactions} rowKey={(row) => String(row.id)} caption="The last 50 ledger rows, newest first" /> : <p className="text-muted-foreground">Nothing yet.</p>}
          </section>
        </div>

        <div className="grid gap-4">
          <form
            aria-label="Give or take credits"
            onSubmit={(event) => {
              event.preventDefault();
              void adjust();
            }}
            className="grid gap-3 rounded-2xl border bg-card p-[18px] shadow-card"
          >
            <h2 className="font-sans text-base font-extrabold">Give or take credits</h2>
            <StackedField id="adjust-amount" label="Credits" help="A number to give (they never expire), or with a minus to take (earliest expiry first)." error={touched ? problems.amount : undefined}>
              <TextBox id="adjust-amount" value={amount} inputMode="numeric" mono onChange={setAmount} error={touched ? problems.amount : undefined} />
            </StackedField>
            <StackedField id="adjust-reason" label="Reason (required)" help="Kept on the ledger row and in the change log." error={touched ? problems.reason : undefined}>
              <TextBox id="adjust-reason" value={reason} onChange={setReason} error={touched ? problems.reason : undefined} />
            </StackedField>
            <Button type="submit" disabled={busy}>{AdjustForm.summary(amount)}</Button>
          </form>
          <section aria-label="Exempt" className="rounded-2xl border bg-card px-[18px] py-2 shadow-card">
            <FieldRow labelId="exempt-label" label="Work costs nothing" help="Still recorded at 0 credits. Off for everyone by default.">
              <Switch aria-labelledby="exempt-label" checked={data.credits_exempt} disabled={busy} onCheckedChange={(next) => void exempt(next)} />
            </FieldRow>
          </section>
        </div>
      </div>
    </div>
  );
}
