"use client";

import { CheckIcon, CircleDashedIcon, CircleIcon, EyeIcon, EyeOffIcon, LockKeyholeIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";

import { useAuth } from "@/components/auth-provider";
import { CodeBoxes } from "@/components/code-boxes";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, type FieldErrors } from "@/lib/api";
import { AuthApi } from "@/lib/auth-api";
import { AuthErrors } from "@/lib/auth-errors";
import { AuthRules } from "@/lib/auth-form";
import { PendingEmail } from "@/lib/pending-email";
import { ResendClock } from "@/lib/resend-clock";
import { cn } from "@/lib/utils";

import { BrandPanel } from "../brand-panel";

const subscribeNothing = () => () => {};

export function ResetForm({ next }: { next: string }) {
  const router = useRouter();
  const { reset } = useAuth();
  const id = useId();
  // The address is in `sessionStorage`, which only the browser has: undefined until the page is running there.
  const hydrated = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const email = hydrated ? new PendingEmail().peek() : undefined;
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<FieldErrors>({});
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [clock] = useState(() => {
    const first = new ResendClock();
    first.start(); // the code was asked for a moment ago
    return first;
  });
  const [, tick] = useState(0);
  const codeInput = useRef<HTMLInputElement>(null);
  const copy = AuthRules.RESET;

  useEffect(() => {
    document.title = `${copy.pageTitle} · Socra`;
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [copy.pageTitle]);
  useEffect(() => {
    if (email) codeInput.current?.focus();
  }, [email]);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email || saving) return;
    const problems = AuthRules.validateReset(code, password);
    setError(null);
    setFields(problems);
    if (Object.keys(problems).length > 0) return;

    setSaving(true);
    try {
      const user = await reset(email, code, password);
      new PendingEmail().clear();
      router.push(AuthRules.destination(user.profile_complete, next));
      router.refresh();
    } catch (err) {
      setError(AuthErrors.message(err));
      setFields(err instanceof ApiError ? err.fields : {});
      if (err instanceof ApiError && err.code === "invalid_code") setCode("");
      setSaving(false);
    }
  };

  const resend = async () => {
    if (!email || !clock.ready()) return;
    setNote(null);
    setError(null);
    clock.start();
    tick((n) => n + 1);
    try {
      await new AuthApi().forgot(email);
      setNote("If that address has an account, we sent a new code. The old one no longer works.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) clock.start(err.retryAfter);
      setError(AuthErrors.message(err));
    }
  };

  const startAgain = () => {
    new PendingEmail().clear();
    router.push(AuthRules.forgotHref(next));
  };

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-6 sm:py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-[28px] border-[1.5px] border-border bg-card shadow-card min-[900px]:grid-cols-[1fr_1.05fr]">
        <BrandPanel mode="login" />

        <div className="flex flex-col gap-5 p-6 sm:p-9">
          <div className="flex flex-col gap-2">
            <span className="grid size-11 place-items-center rounded-full bg-primary-soft text-primary-text">
              <LockKeyholeIcon className="size-5" aria-hidden="true" />
            </span>
            <h1 className="font-heading text-2xl font-semibold tracking-tight">{copy.title}</h1>
            {email === undefined ? null : email ? (
              <p className="text-muted-foreground">{AuthRules.resetDescription(email)}</p>
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

              <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
                <div className="flex flex-col gap-1.5">
                  <CodeBoxes ref={codeInput} id={`${id}-code`} label={copy.label} value={code} onChange={setCode} invalid={!!fields.code} describedBy={`${id}-hint`} />
                  <p id={`${id}-hint`} className="text-sm text-muted-foreground">
                    {fields.code ? fields.code.join(" ") : copy.hint}
                  </p>
                </div>
                <FormField id="new_password" label={copy.password} errors={fields.new_password}>
                  <div className="relative">
                    <Input
                      id="new_password"
                      name="new_password"
                      type={shown ? "text" : "password"}
                      autoComplete="new-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      aria-invalid={!!fields.new_password}
                      aria-describedby={fields.new_password ? "new_password-error" : "password-rules"}
                      className="pr-16"
                    />
                    <button
                      type="button"
                      onClick={() => setShown((value) => !value)}
                      aria-pressed={shown}
                      className="absolute inset-y-0 right-1 my-auto flex h-7 items-center gap-1 rounded-md px-2 text-xs font-extrabold text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      {shown ? <EyeOffIcon className="size-3.5" aria-hidden="true" /> : <EyeIcon className="size-3.5" aria-hidden="true" />}
                      {shown ? "Hide" : "Show"}
                      <span className="sr-only"> password</span>
                    </button>
                  </div>
                  <ul id="password-rules" aria-live="polite" className="flex flex-col gap-1 text-sm">
                    {AuthRules.checklist(password).map((item) => (
                      <li key={item.label} className={cn("flex items-center gap-2", item.met ? "text-success-text" : "text-muted-foreground")}>
                        {item.met ? (
                          <CheckIcon className="size-4 shrink-0" aria-label="done" />
                        ) : item.met === null ? (
                          <CircleDashedIcon className="size-4 shrink-0" aria-hidden="true" />
                        ) : (
                          <CircleIcon className="size-4 shrink-0" aria-hidden="true" />
                        )}
                        {item.label}
                      </li>
                    ))}
                  </ul>
                </FormField>
                <Button type="submit" size="lg" disabled={saving} className="h-11">
                  {saving ? copy.pending : copy.submit}
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
