"use client";

import { keepPreviousData, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { MailQuestionIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { type Column, DataTable } from "@/components/console/data-table";
import { EmptyState } from "@/components/console/empty-state";
import { ErrorState } from "@/components/console/error-state";
import { notFoundIfRefused } from "@/components/console/not-found-guard";
import { PageHeader } from "@/components/console/page-header";
import { ReasonAction } from "@/components/console/signin/reason-action";
import { StatusPill } from "@/components/console/status-pill";
import { useDebouncedText } from "@/components/console/use-debounced-text";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { consoleApi } from "@/lib/console-api";
import { ConsoleFailure } from "@/lib/console-failure";
import { PeopleUrl } from "@/lib/console-people";
import { SigninFailure } from "@/lib/console-signin/failure";
import { SigninWords } from "@/lib/console-signin/forms";
import { signinQueries } from "@/lib/console-signin/queries";
import type { PendingSignupRow, SignupApproved } from "@/lib/console-signin/types";

/** The people who registered and are still waiting for their code. They are not accounts yet, so nothing else in the console shows them. */
export function SignupsView() {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const q = PeopleUrl.search(useSearchParams());
  const [text, setText] = useDebouncedText(q, (next) => router.replace(`${pathname}${PeopleUrl.searchQuery(next)}`, { scroll: false }));
  const list = notFoundIfRefused(useInfiniteQuery({ ...signinQueries.signups(q), placeholderData: keepPreviousData }));
  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.results) ?? [], [list.data]);
  const [busy, setBusy] = useState(false);
  const [approving, setApproving] = useState<PendingSignupRow | null>(null);
  const [approved, setApproved] = useState<SignupApproved | null>(null);

  const act = async <T,>(call: () => Promise<T>, done: (result: T) => string): Promise<boolean> => {
    setBusy(true);
    try {
      toast.success(done(await call()));
      await queryClient.invalidateQueries({ queryKey: ["console"] });
      return true;
    } catch (failure) {
      toast.error(SigninFailure.message(failure) ?? ConsoleFailure.of(failure).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<PendingSignupRow>[] = [
    {
      key: "who",
      header: "Waiting",
      cell: (row) => (
        <div className="min-w-0">
          <span className="font-extrabold">{row.name.trim() || "No name"}</span>
          <span className="block max-w-64 truncate text-xs font-semibold text-muted-foreground" title={row.email}>
            {row.email}
          </span>
        </div>
      ),
    },
    { key: "made", header: "Registered", cell: (row) => SigninWords.when(row.created_at) },
    { key: "expires", header: "Sign-up runs out", cell: (row) => SigninWords.when(row.expires_at) },
    {
      key: "code",
      header: "Live code",
      cell: (row) => (row.code_tries === null ? <span className="text-muted-foreground">None</span> : `${row.code_tries} of ${row.code_max_tries} tries, until ${SigninWords.when(row.code_expires_at)}`),
    },
    {
      key: "lock",
      header: "Lock",
      cell: (row) => (row.locked_until && new Date(row.locked_until) > new Date() ? <StatusPill tone="bad">Locked until {SigninWords.when(row.locked_until)}</StatusPill> : <StatusPill tone="off">Not locked</StatusPill>),
    },
    {
      key: "actions",
      header: "Actions",
      cell: (row) => (
        <div className="flex flex-wrap gap-1.5">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => consoleApi.resendSignup(row.id), (r) => r.note)}>
            Send a new code
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => consoleApi.unlockSignup(row.id), (r) => r.note)}>
            Unlock
          </Button>
          <Button size="sm" disabled={busy} onClick={() => { setApproved(null); setApproving(row); }}>
            Approve…
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Waiting for a code"
        description="People who registered and have not entered their code yet. They are not accounts until they do."
        actions={
          <label className="flex min-w-0 items-center gap-1.5 rounded-[10px] border bg-card px-2.5 py-1.5 text-muted-foreground focus-within:ring-3 focus-within:ring-ring/50 sm:w-64">
            <SearchIcon className="size-[15px] shrink-0" aria-hidden="true" />
            <input
              type="search"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Email"
              aria-label="Search sign-ups"
              className="min-w-0 flex-1 bg-transparent font-semibold text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>
        }
      />

      {approved ? (
        <section aria-label="Approved" className="mb-4 grid gap-2 rounded-2xl border border-success/40 bg-success-soft p-[18px] shadow-card">
          <h2 className="font-sans text-base font-extrabold text-success-text">Approved</h2>
          <p className="font-semibold">{approved.note}</p>
          <p>
            <Link href={`/console/learners/${approved.learner_id}/verification`} className="font-extrabold text-primary-text hover:underline">
              Open their sign-in
            </Link>
          </p>
        </section>
      ) : null}

      {approving ? (
        <div className="mb-4">
          <ReasonAction
            id="approve-reason"
            title={`Approve ${approving.email}`}
            warning="Confirm this person out of band first (a message from the address on file, or in person). The account is made with no password: they sign in with Google, or choose a password with “Forgot password”."
            buttonLabel="Approve and make the account"
            busy={busy}
            onSubmit={async (reason) => {
              setBusy(true);
              try {
                const result = await consoleApi.approveSignup(approving.id, reason);
                setApproved(result);
                setApproving(null);
                await queryClient.invalidateQueries({ queryKey: ["console"] });
                return true;
              } catch (failure) {
                toast.error(SigninFailure.message(failure) ?? ConsoleFailure.of(failure).message);
                return false;
              } finally {
                setBusy(false);
              }
            }}
          />
          <div className="mt-2">
            <Button variant="ghost" size="sm" onClick={() => setApproving(null)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      <section aria-label="Sign-ups waiting" aria-busy={list.isFetching && !list.isFetchingNextPage} className="min-w-0 rounded-2xl border bg-card shadow-card">
        <div className="px-[18px] py-3">
          {list.error && !list.data ? (
            <ErrorState message="The sign-ups could not be loaded." onRetry={() => void list.refetch()} />
          ) : list.isPending ? (
            <div role="status" aria-label="Loading sign-ups" className="grid gap-2">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} className="h-11 w-full" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState icon={MailQuestionIcon} title={q ? `No sign-ups match “${q}”` : "Nobody is waiting"} description={q ? "Try part of an email address." : "People who register and have not entered their code show up here."} />
          ) : (
            <DataTable columns={columns} rows={rows} rowKey={(row) => row.id} caption="Sign-ups waiting for a code, newest first" />
          )}
          {list.hasNextPage ? (
            <div className="mt-3 text-center">
              <Button variant="outline" size="sm" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
                {list.isFetchingNextPage ? "Loading…" : "Show more"}
              </Button>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
