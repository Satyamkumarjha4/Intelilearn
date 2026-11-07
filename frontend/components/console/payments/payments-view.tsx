"use client";

import { keepPreviousData, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCardIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/console/empty-state";
import { ErrorState } from "@/components/console/error-state";
import { SelectBox, TextBox } from "@/components/console/field-row";
import { KpiTile } from "@/components/console/kpi-tile";
import { notFoundIfRefused } from "@/components/console/not-found-guard";
import { PageHeader } from "@/components/console/page-header";
import { StatusPill } from "@/components/console/status-pill";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { useDebouncedText } from "@/components/console/use-debounced-text";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { consoleApi } from "@/lib/console-api";
import { RefundForm } from "@/lib/console-credits/forms";
import { ConsolePaymentWords } from "@/lib/console-credits/payment-words";
import { creditQueries } from "@/lib/console-credits/queries";
import type { PaymentRow, RefundRow } from "@/lib/console-credits/types";
import { ConsoleFailure } from "@/lib/console-failure";
import { ConsoleFormat } from "@/lib/console-format";

const STATUSES = [
  { value: "", label: "Any state" },
  ...Object.entries(ConsolePaymentWords.STATUS).map(([value, { label }]) => ({ value, label })),
];

function RefundBox({ order, onDone }: { order: PaymentRow; onDone: () => void }) {
  // Made when the form is drawn (here), so sending it twice refunds once.
  const [token] = useState(() => crypto.randomUUID());
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const typed = RefundForm.amount(amount);
  const left = ConsolePaymentWords.refundable(order);

  const send = async () => {
    if (!typed.ok) return;
    setBusy(true);
    try {
      const result = await consoleApi.refund(order.id, RefundForm.body(token, typed.rupees));
      toast.success(result.message.charAt(0).toUpperCase() + result.message.slice(1));
      onDone();
    } catch (failure) {
      toast.error(ConsoleFailure.of(failure).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      aria-label={`Refund ${order.learner.email}'s payment`}
      onSubmit={(event) => {
        event.preventDefault();
        void send();
      }}
      className="mt-2 flex flex-wrap items-end gap-2"
    >
      <div className="grid gap-1">
        <label htmlFor={`refund-${order.id}`} className="text-[12.5px] font-bold">
          Refund (₹), up to {ConsolePaymentWords.paise(left)}
        </label>
        <div className="w-44">
          <TextBox id={`refund-${order.id}`} value={amount} inputMode="decimal" mono placeholder="all that remains" onChange={setAmount} error={typed.ok ? undefined : typed.error} />
        </div>
      </div>
      <Button type="submit" size="sm" disabled={busy || !typed.ok}>
        {busy ? "Asking…" : "Refund"}
      </Button>
      {!typed.ok ? <p role="alert" className="w-full text-xs font-bold text-destructive-text">{typed.error}</p> : null}
    </form>
  );
}

function RefundLine({ refund, onDone }: { refund: RefundRow; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const tone = ConsolePaymentWords.REFUND[refund.state].tone;
  const markFailed = async () => {
    setBusy(true);
    try {
      await consoleApi.markRefundFailed(refund.id);
      toast.success("Marked as failed. That amount can be refunded again.");
      onDone();
    } catch (failure) {
      toast.error(ConsoleFailure.of(failure).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="flex flex-wrap items-center gap-2 text-[13px] font-semibold">
      <StatusPill tone={tone}>{ConsolePaymentWords.REFUND[refund.state].label}</StatusPill>
      <span>{ConsolePaymentWords.paise(refund.amount_paise)}</span>
      <span className="font-mono text-xs text-muted-foreground">{refund.refund_ref || "no reference"}</span>
      <span className="text-xs text-muted-foreground">asked {ConsoleFormat.dayLong(refund.created_at)}</span>
      {refund.can_mark_failed ? (
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void markFailed()}>
          Mark as failed
        </Button>
      ) : null}
    </li>
  );
}

function OrderCard({ order, onDone }: { order: PaymentRow; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const state = ConsolePaymentWords.STATUS[order.status];
  const refundable = ConsolePaymentWords.refundable(order) > 0;
  return (
    <li className="grid gap-1.5 border-b border-border/60 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <StatusPill tone={state.tone}>{state.label}</StatusPill>
        <b className="tabular-nums">{ConsolePaymentWords.paise(order.amount_paise)}</b>
        <span className="font-semibold">{order.plan}</span>
        <span className="font-semibold text-muted-foreground">{order.learner.name.trim() || order.learner.email}</span>
        <span className="rounded-md bg-muted px-1.5 py-px text-[11.5px] font-extrabold uppercase">{order.gateway}</span>
        <span className="text-xs font-semibold text-muted-foreground">{ConsoleFormat.dayLong(order.created_at)}</span>
        {order.refunded_paise > 0 ? <span className="text-xs font-extrabold text-destructive-text">refunded {ConsolePaymentWords.paise(order.refunded_paise)}</span> : null}
        {order.shortfall_credits > 0 ? <span className="text-xs font-extrabold text-marigold-text">{order.shortfall_credits} credits could not be taken back</span> : null}
      </div>
      <p className="font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {order.provider_ref || "no checkout"}{order.payment_ref ? ` · ${order.payment_ref}` : ""}
      </p>
      {order.refunds.length ? (
        <ul aria-label="Refunds asked for" className="grid gap-1">
          {order.refunds.map((refund) => (
            <RefundLine key={refund.id} refund={refund} onDone={onDone} />
          ))}
        </ul>
      ) : null}
      {refundable ? (
        open ? (
          <RefundBox order={order} onDone={() => { setOpen(false); onDone(); }} />
        ) : (
          <div><Button variant="outline" size="sm" onClick={() => setOpen(true)}>Refund…</Button></div>
        )
      ) : null}
    </li>
  );
}

/** Payments: orders with their state, gateway and refunds, the refund action (a token per form, an optional amount), and the credits a refund could not take back. */
export function PaymentsView() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [gateway, setGateway] = useState("");
  const [q, setQ] = useState("");
  const [text, setText] = useDebouncedText(q, setQ);
  const filters = { status, gateway, q };

  const list = notFoundIfRefused(useInfiniteQuery({ ...creditQueries.payments(filters), placeholderData: keepPreviousData }));
  const shortfalls = useConsoleQuery(creditQueries.shortfalls());
  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.results) ?? [], [list.data]);
  const summary = list.data?.pages[0]?.summary;
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["console", "payments"] });
  const gateways = useMemo(() => ["", ...new Set(rows.map((row) => row.gateway))], [rows]);

  return (
    <div>
      <PageHeader
        title="Payments"
        description="Every order, what became of it, and its refunds. Credits are taken back when the provider's refund arrives, never here."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <SelectBox id="payments-status" ariaLabel="State" value={status} onChange={setStatus} options={STATUSES} className="w-44" />
            <SelectBox id="payments-gateway" ariaLabel="Provider" value={gateway} onChange={setGateway} options={gateways.map((value) => ({ value, label: value || "Any provider" }))} className="w-36" />
            <div className="w-56">
              <TextBox id="payments-search" value={text} placeholder="Learner or reference" onChange={setText} />
            </div>
          </div>
        }
      />

      {summary ? (
        <div className="mb-4 grid grid-cols-3 gap-4 max-[900px]:grid-cols-1">
          <KpiTile data={{ label: "Waiting for payment", value: String(summary.orders_waiting), detail: "orders not paid yet" }} />
          <KpiTile data={{ label: "Refunds waiting", value: String(summary.refunds_waiting), detail: "asked for, not yet confirmed" }} />
          <KpiTile data={{ label: "Could not take back", value: String(summary.shortfalls), detail: "refunds of credits already spent" }} />
        </div>
      ) : null}

      <section aria-label="Orders" aria-busy={list.isFetching && !list.isFetchingNextPage} className="rounded-2xl border bg-card px-[18px] py-2 shadow-card">
        {list.error && !list.data ? (
          <ErrorState message="The payments could not be loaded." onRetry={() => void list.refetch()} />
        ) : list.isPending ? (
          <div role="status" aria-label="Loading payments" className="grid gap-2 py-3">
            {Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-14 w-full" />)}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState icon={CreditCardIcon} title="No payments match" description="Orders show up here as learners buy credits." />
        ) : (
          <ul aria-label="Orders, newest first">
            {rows.map((order) => <OrderCard key={order.id} order={order} onDone={refresh} />)}
          </ul>
        )}
        {list.hasNextPage ? (
          <div className="py-3 text-center">
            <Button variant="outline" size="sm" disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
              {list.isFetchingNextPage ? "Loading…" : "Show more"}
            </Button>
          </div>
        ) : null}
      </section>

      {shortfalls.data && shortfalls.data.length ? (
        <section aria-label="Credits a refund could not take back" className="mt-4 rounded-2xl border bg-card p-[18px] shadow-card">
          <h2 className="mb-1 font-sans text-base font-extrabold">Credits a refund could not take back</h2>
          <p className="mb-2 text-[13px] font-semibold text-muted-foreground">These credits were already spent when the refund arrived. Support decides what to do.</p>
          <ul className="grid gap-1 text-[13px] font-semibold">
            {shortfalls.data.map((row) => (
              <li key={row.id}>
                <b>{row.shortfall_credits} credits</b> · {row.learner?.email ?? "unknown learner"} · {row.kind} of {ConsolePaymentWords.paise(row.amount_paise)} via {row.gateway} · {ConsoleFormat.dayLong(row.received_at)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
