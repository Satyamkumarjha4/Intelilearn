"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Trash2Icon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { StackedField, TextBox } from "@/components/console/field-row";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { Button } from "@/components/ui/button";
import { consoleApi } from "@/lib/console-api";
import { EraseForm } from "@/lib/console-credits/forms";
import { creditQueries } from "@/lib/console-credits/queries";
import { ConsoleFailure } from "@/lib/console-failure";

/** The danger zone of a learner's page: says what deleting their data would take and keep, and does it once the account's email is typed. */
export function ErasePanel({ learnerId }: { learnerId: string }) {
  const queryClient = useQueryClient();
  const { data, error } = useConsoleQuery(creditQueries.erasure(learnerId));
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | undefined>();

  if (error || !data) return null;
  const blocked = EraseForm.blocked(data.blocked);
  const ready = EraseForm.matches(typed, data.learner.email);

  const erase = async () => {
    setBusy(true);
    setProblem(undefined);
    try {
      const result = await consoleApi.eraseLearner(learnerId, typed.trim());
      toast.success(EraseForm.done(result));
      setTyped("");
      await queryClient.invalidateQueries({ queryKey: ["console"] });
    } catch (failure) {
      const fields = ConsoleFailure.of(failure).fields;
      setProblem(fields.confirm_email?.[0] ?? ConsoleFailure.of(failure).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Delete this learner's data" className="grid gap-3 rounded-2xl border border-destructive/40 bg-card p-[18px] shadow-card">
      <h2 className="flex items-center gap-1.5 font-sans text-base font-extrabold text-destructive-text">
        <Trash2Icon className="size-4" aria-hidden="true" /> Delete this learner&apos;s data
      </h2>
      {blocked ? (
        <p role="note" className="text-[13px] font-semibold text-muted-foreground">{blocked}</p>
      ) : (
        <>
          <div className="grid gap-1 text-[13px] font-semibold">
            <p>
              <b>Deleted for good:</b> {data.lessons} {data.lessons === 1 ? "lesson" : "lessons"} and {data.quizzes} {data.quizzes === 1 ? "quiz" : "quizzes"} with their
              answers and checkpoints, the streak, {data.refresh_tokens} sign-in{data.refresh_tokens === 1 ? "" : "s"} and the admin&apos;s log about this account. The
              profile, name and email are emptied.
            </p>
            <p>
              <b>Written off:</b> {data.credits_to_forfeit} credits{data.open_reserves ? `, after releasing ${data.open_reserves} open reserve${data.open_reserves === 1 ? "" : "s"}` : ""}.
            </p>
            <p className="text-muted-foreground">
              <b>Kept, with no name or email:</b> {data.ledger_rows_kept} ledger rows, {data.purchases_kept} purchases and {data.orders_kept} orders (the law and the books ask for them). The
              payment provider keeps its own copy. This cannot be undone.
            </p>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (ready) void erase();
            }}
            className="grid gap-2"
          >
            <StackedField id="erase-confirm" label="Type the account's email to confirm" help={data.learner.email} error={problem}>
              <TextBox id="erase-confirm" value={typed} onChange={setTyped} error={problem} />
            </StackedField>
            <div>
              <Button type="submit" variant="destructive" disabled={!ready || busy}>
                {busy ? "Deleting…" : "Delete this learner's data"}
              </Button>
            </div>
          </form>
        </>
      )}
    </section>
  );
}
