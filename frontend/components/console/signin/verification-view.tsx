"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { type Column, DataTable } from "@/components/console/data-table";
import { ErrorState } from "@/components/console/error-state";
import { KpiTile } from "@/components/console/kpi-tile";
import { PageHeader } from "@/components/console/page-header";
import { CardSkeleton, KpiRowSkeleton } from "@/components/console/skeletons";
import { ReasonAction } from "@/components/console/signin/reason-action";
import { StatusPill } from "@/components/console/status-pill";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { Button } from "@/components/ui/button";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { SigninFailure } from "@/lib/console-signin/failure";
import { SigninWords } from "@/lib/console-signin/forms";
import { signinQueries } from "@/lib/console-signin/queries";
import type { VerificationCodeRow, VerificationMailRow, VerificationPanel } from "@/lib/console-signin/types";

const codeColumns: Column<VerificationCodeRow>[] = [
  { key: "purpose", header: "For", cell: (row) => SigninWords.purpose(row.purpose) },
  { key: "sent", header: "Sent", cell: (row) => SigninWords.when(row.created_at) },
  { key: "expires", header: "Runs out", cell: (row) => SigninWords.when(row.expires_at) },
  { key: "tries", header: "Tries", numeric: true, cell: (row) => `${row.tries} of ${row.max_tries}` },
  { key: "state", header: "What happened", cell: (row) => SigninWords.codeState(row.state) },
];
const mailColumns: Column<VerificationMailRow>[] = [
  { key: "kind", header: "Email", cell: (row) => <span className="font-mono text-[12.5px]">{row.kind}</span> },
  { key: "when", header: "Queued", cell: (row) => SigninWords.when(row.created_at) },
  { key: "status", header: "Status", cell: (row) => `${row.status}${row.error ? `: ${row.error}` : ""}` },
];

/** One learner's sign-in for support: why they may be stuck, and the three things staff can do about it. Never shows a code. */
export function VerificationView({ learnerId }: { learnerId: string }) {
  const queryClient = useQueryClient();
  const { data, error, isPending, refetch } = useConsoleQuery(signinQueries.verification(learnerId));
  const [busy, setBusy] = useState(false);

  const header = (
    <>
      <Link href="/console/learners" className="mb-2 inline-flex items-center gap-1 text-[13px] font-extrabold text-primary-text hover:underline">
        <ArrowLeftIcon className="size-3.5" aria-hidden="true" /> Learners
      </Link>
      <PageHeader title={data ? data.learner.name.trim() || data.learner.email : "Sign-in"} description={data ? data.learner.email : undefined} />
    </>
  );
  if (error && !data) return <>{header}<ErrorState message="This learner's sign-in could not be loaded." onRetry={() => void refetch()} /></>;
  if (isPending || !data) {
    return (
      <div aria-busy="true">
        {header}
        <KpiRowSkeleton count={3} />
        <div className="mt-4"><CardSkeleton height={160} /></div>
      </div>
    );
  }

  const run = async (act: () => Promise<VerificationPanel>, done: string): Promise<boolean> => {
    setBusy(true);
    try {
      queryClient.setQueryData(signinQueries.verification(learnerId).queryKey, await act());
      await queryClient.invalidateQueries({ queryKey: ["console"], refetchType: "none" });
      toast.success(done);
      return true;
    } catch (failure) {
      toast.error(SigninFailure.message(failure) ?? ConsoleFailure.of(failure).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const { state } = data;
  return (
    <div>
      {header}
      <div className="grid grid-cols-3 gap-4 max-[900px]:grid-cols-1">
        <KpiTile data={{ label: "Email", value: state.verified ? "Verified" : "Not verified", detail: SigninWords.source(state.source), small: true }} />
        <KpiTile data={{ label: "Can sign in with", value: data.sign_in_methods.length ? String(data.sign_in_methods.length) : "0", detail: SigninWords.methods(data.sign_in_methods) }} />
        <KpiTile
          data={{
            label: "Lock",
            value: data.lock ? "Locked" : "Not locked",
            detail: data.lock ? `until ${SigninWords.when(data.lock.locked_until)} (${data.lock.strikes} dead codes)` : "codes can be checked",
            small: true,
          }}
        />
      </div>

      {state.erased || state.closed ? (
        <p role="note" className="mt-4 rounded-xl border bg-muted px-4 py-3 font-semibold">
          {state.erased ? "This account has been erased." : "This account is closed."} Nothing can be done to its sign-in from here.
        </p>
      ) : null}

      <div className="mt-4 grid items-start gap-4 min-[1000px]:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 gap-4">
          <section aria-label="Last codes" className="rounded-2xl border bg-card p-[18px] shadow-card">
            <h2 className="mb-2 font-sans text-base font-extrabold">Last codes</h2>
            {data.codes.length ? <DataTable columns={codeColumns} rows={data.codes} rowKey={(row) => `${row.created_at}-${row.purpose}`} caption="The last five codes, newest first. The code itself is never shown." /> : <p className="text-muted-foreground">No code has been sent.</p>}
          </section>
          <section aria-label="Last emails" className="rounded-2xl border bg-card p-[18px] shadow-card">
            <h2 className="mb-2 font-sans text-base font-extrabold">Last emails to this address</h2>
            {data.mail.length ? <DataTable columns={mailColumns} rows={data.mail} rowKey={(row) => `${row.created_at}-${row.kind}`} caption="The last five emails sent to the address, newest first" /> : <p className="text-muted-foreground">Nothing has been sent.</p>}
          </section>
          <section aria-label="How the account was made" className="rounded-2xl border bg-card p-[18px] shadow-card">
            <h2 className="mb-2 font-sans text-base font-extrabold">How the account was made</h2>
            {data.signup_record ? (
              <p className="font-semibold">
                {SigninWords.method(data.signup_record.method)} on {SigninWords.when(data.signup_record.created_at)}, from {data.signup_record.ip ?? "an unknown address"}, email domain{" "}
                {data.signup_record.email_domain}.
              </p>
            ) : (
              <p className="text-muted-foreground">No record (they are kept for 30 days).</p>
            )}
            {data.identities.length ? (
              <ul className="mt-2 grid gap-1 font-semibold">
                {data.identities.map((identity) => (
                  <li key={identity.provider}>
                    {SigninWords.method(identity.provider)} linked {SigninWords.when(identity.linked_at)}
                    {identity.last_sign_in_at ? `, last used ${SigninWords.when(identity.last_sign_in_at)}` : ""}
                    {identity.hosted_domain ? `, workspace ${identity.hosted_domain}` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        </div>

        <div className="grid gap-4">
          <section aria-label="Actions" className="grid gap-3 rounded-2xl border bg-card p-[18px] shadow-card">
            <h2 className="font-sans text-base font-extrabold">What staff can do</h2>
            <StatusPill tone={state.verified ? "ok" : "warn"}>{state.verified ? `Verified${state.verified_at ? ` ${SigninWords.when(state.verified_at)}` : ""}` : "Not verified"}</StatusPill>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" disabled={busy || !state.can_resend} onClick={() => void run(() => consoleApi.resendVerification(learnerId), "A new code is on its way to their address.")}>
                Send a new code
              </Button>
              <Button variant="outline" size="sm" disabled={busy || !state.can_unlock} onClick={() => void run(() => consoleApi.unlockVerification(learnerId), "Unlocked. Their codes can be checked again.")}>
                Unlock this email
              </Button>
            </div>
            <p className="text-xs font-semibold text-muted-foreground">Unlock also cancels any live code, so send a new one after it.</p>
          </section>
          {state.can_mark_verified ? (
            <ReasonAction
              id="mark-verified-reason"
              title="Mark the email verified"
              warning="Use this only after you have confirmed the person out of band (a message from the address on file, or in person). It gives their signup credits once."
              buttonLabel="Mark verified"
              busy={busy}
              onSubmit={(reason) => run(() => consoleApi.markVerified(learnerId, reason), "Marked verified. The signup credits were given once.")}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
