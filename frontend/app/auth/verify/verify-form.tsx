"use client";

import { MailCheckIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";

import { useAuth } from "@/components/auth-provider";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { CodeBoxes } from "@/components/code-boxes";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { AuthApi, type CodePurpose } from "@/lib/auth-api";
import { AuthErrors } from "@/lib/auth-errors";
import { AuthRules } from "@/lib/auth-form";
import { CodeEntry } from "@/lib/code-entry";
import { PendingEmail } from "@/lib/pending-email";
import { ResendClock } from "@/lib/resend-clock";

import { BrandPanel } from "../brand-panel";

const subscribeNothing = () => () => {};

export function VerifyForm({ purpose, next }: { purpose: CodePurpose; next: string }) {
  const router = useRouter();
  const { verify } = useAuth();
  const id = useId();
  // The address is in `sessionStorage`, which only the browser has: undefined until the page is running there.
  const hydrated = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const email = hydrated ? new PendingEmail().peek() : undefined;
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // The first code was sent a moment ago, so the wait for another starts now.
  const [clock] = useState(() => {
    const first = new ResendClock();
    first.start();
    return first;
  });
  const [, tick] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = `${AuthRules.VERIFY.pageTitle} · Socra`;
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (email) input.current?.focus();
  }, [email]);

  const submit = async (value: string) => {
    if (!email || checking || !CodeEntry.isComplete(value)) return;
    setChecking(true);
    setError(null);
    try {
      const user = await verify(email, CodeEntry.digits(value), purpose);
      new PendingEmail().clear();
      router.push(AuthRules.destination(user.profile_complete, next));
      router.refresh();
    } catch (err) {
      setError(AuthErrors.message(err));
      setTyped("");
      setChecking(false);
      input.current?.focus();
    }
  };

  const onType = (raw: string) => {
    const digits = CodeEntry.digits(raw);
    setTyped(digits);
    setError(null);
    if (CodeEntry.isComplete(digits)) void submit(digits);
  };

  const resend = async () => {
    if (!email || !clock.ready()) return;
    setNote(null);
    setError(null);
    clock.start();
    tick((n) => n + 1);
    try {
      await new AuthApi().resend(email, purpose);
      setNote("We sent a new code. The old one no longer works.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) clock.start(err.retryAfter);
      setError(AuthErrors.message(err));
    }
  };

  const startAgain = () => {
    new PendingEmail().clear();
    router.push(AuthRules.href("register", next));
  };

  const copy = AuthRules.VERIFY;
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-6 sm:py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-[28px] border-[1.5px] border-border bg-card shadow-card min-[900px]:grid-cols-[1fr_1.05fr]">
        <BrandPanel mode={purpose === "login" ? "login" : "register"} />

        <div className="flex flex-col gap-5 p-6 sm:p-9">
          <div className="flex flex-col gap-2">
            <span className="grid size-11 place-items-center rounded-full bg-primary-soft text-primary-text">
              <MailCheckIcon className="size-5" aria-hidden="true" />
            </span>
            <h1 className="font-heading text-2xl font-semibold tracking-tight">{copy.title}</h1>
            {email === undefined ? null : email ? (
              <p className="text-muted-foreground">{AuthRules.verifyDescription(email)}</p>
            ) : (
              <p className="text-muted-foreground">{copy.lost}</p>
            )}
          </div>

          {email === null && (
            <Button type="button" size="lg" className="h-11" onClick={startAgain}>
              {copy.start}
            </Button>
          )}

          {email && (
            <>
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              {note && (
                <Alert>
                  <AlertDescription role="status">{note}</AlertDescription>
                </Alert>
              )}

              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void submit(typed);
                }}
                className="flex flex-col gap-4"
                noValidate
              >
                <CodeBoxes ref={input} id={`${id}-code`} label={copy.label} value={typed} onChange={onType} invalid={!!error} describedBy={`${id}-hint`} />
                <p id={`${id}-hint`} className="text-sm text-muted-foreground">
                  {copy.hint}
                </p>
                <Button type="submit" size="lg" disabled={checking || !CodeEntry.isComplete(typed)} className="h-11">
                  {checking ? copy.pending : copy.submit}
                </Button>
              </form>

              <div className="flex flex-col items-start gap-2 text-sm">
                <button
                  type="button"
                  onClick={() => void resend()}
                  disabled={!clock.ready()}
                  className="rounded-md font-extrabold text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 disabled:text-muted-foreground disabled:no-underline"
                >
                  {clock.label()}
                </button>
                <button
                  type="button"
                  onClick={startAgain}
                  className="rounded-md font-extrabold text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {copy.different}
                </button>
              </div>
            </>
          )}

          <p className="text-center text-sm text-muted-foreground">
            <Link href={AuthRules.href("login", next)} className="font-bold underline underline-offset-4">
              Back to sign in
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
