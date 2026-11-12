"use client";

import { PartyPopperIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiClient, type FieldErrors } from "@/lib/api";
import { AuthApi } from "@/lib/auth-api";
import { AuthErrors } from "@/lib/auth-errors";
import { AuthRules } from "@/lib/auth-form";
import { BrowserTimezone } from "@/lib/browser-timezone";

import { BrandPanel } from "../brand-panel";

type Waiting = { email: string; name: string };

/**
 * The last step of a first sign-in with a provider. Nothing exists yet: no account, no credits. The person gives their name
 * (the provider's is offered) and agrees to the terms, and only then is the account made. The address is shown, not editable:
 * it is the one the provider confirmed. With no live ticket (it expires after a few minutes) the screen says so and goes back.
 */
export function FinishForm({ next }: { next: string }) {
  const router = useRouter();
  const { setUser } = useAuth();
  const [waiting, setWaiting] = useState<Waiting | null | undefined>(undefined); // undefined: still asking
  const [name, setName] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const copy = AuthRules.FINISH;

  useEffect(() => {
    let active = true;
    new AuthApi(apiClient)
      .finishInfo()
      .then((found) => {
        if (!active) return;
        setWaiting(found);
        setName(found.name);
      })
      .catch(() => active && setWaiting(null));
    return () => {
      active = false;
    };
  }, []);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const problems = AuthRules.validateFinish(name, acceptedTerms);
    setError(null);
    setFields(problems);
    if (Object.keys(problems).length > 0) return;

    setSaving(true);
    try {
      const user = await new AuthApi(apiClient).finish(name.trim(), acceptedTerms, BrowserTimezone.detect());
      setUser(user);
      router.push(AuthRules.destination(user.profile_complete, next));
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === "finish_expired") setWaiting(null);
      setError(AuthErrors.message(err));
      setFields(err instanceof ApiError ? err.fields : {});
      setSaving(false);
    }
  };

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-6 sm:py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-[28px] border-[1.5px] border-border bg-card shadow-card min-[900px]:grid-cols-[1fr_1.05fr]">
        <BrandPanel mode="register" />

        <div className="flex flex-col gap-5 p-6 sm:p-9">
          <div className="flex flex-col gap-2">
            <span className="grid size-11 place-items-center rounded-full bg-primary-soft text-primary-text">
              <PartyPopperIcon className="size-5" aria-hidden="true" />
            </span>
            <h1 className="font-heading text-2xl font-semibold tracking-tight">{copy.title}</h1>
            {waiting ? <p className="text-muted-foreground">{copy.description}</p> : null}
          </div>

          {waiting === null && (
            <>
              <Alert variant="destructive">
                <AlertDescription>
                  {copy.expired} {copy.expiredHelp}
                </AlertDescription>
              </Alert>
              <Button type="button" size="lg" className="h-11" onClick={() => router.push(AuthRules.href("login", next))}>
                {copy.start}
              </Button>
            </>
          )}

          {waiting && (
            <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <FormField id="email" label={copy.email}>
                <Input id="email" name="email" type="email" value={waiting.email} readOnly aria-readonly="true" autoComplete="email" />
              </FormField>
              <FormField id="name" label="Name" errors={fields.name}>
                <Input
                  id="name"
                  name="name"
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  aria-invalid={!!fields.name}
                  aria-describedby={fields.name ? "name-error" : undefined}
                />
              </FormField>
              <div className="flex flex-col gap-1.5">
                <label className="flex items-start gap-3 text-sm">
                  <input
                    type="checkbox"
                    name="accept_terms"
                    checked={acceptedTerms}
                    onChange={(event) => setAcceptedTerms(event.target.checked)}
                    aria-invalid={!!fields.accept_terms}
                    aria-describedby={fields.accept_terms ? "accept_terms-error" : undefined}
                    className="mt-0.5 size-5 shrink-0 accent-primary focus-visible:ring-3 focus-visible:ring-ring/50"
                  />
                  <span>
                    {AuthRules.CONSENT_LABEL}{" "}
                    <Link href="/terms" target="_blank" className="font-bold underline underline-offset-4">
                      Terms of Use
                    </Link>{" "}
                    and{" "}
                    <Link href="/privacy" target="_blank" className="font-bold underline underline-offset-4">
                      Privacy Policy
                    </Link>
                    .
                  </span>
                </label>
                {fields.accept_terms && (
                  <p id="accept_terms-error" className="text-sm text-destructive">
                    {fields.accept_terms.join(" ")}
                  </p>
                )}
              </div>
              <Button type="submit" size="lg" disabled={saving} className="mt-1 h-11">
                {saving ? copy.pending : copy.submit}
              </Button>
            </form>
          )}
        </div>
      </div>
    </main>
  );
}
