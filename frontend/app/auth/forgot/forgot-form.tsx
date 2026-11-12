"use client";

import { KeyRoundIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { FormField } from "@/components/form-field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, type FieldErrors } from "@/lib/api";
import { AuthApi } from "@/lib/auth-api";
import { AuthErrors } from "@/lib/auth-errors";
import { AuthRules } from "@/lib/auth-form";
import { PendingEmail } from "@/lib/pending-email";

import { BrandPanel } from "../brand-panel";

export function ForgotForm({ next }: { next: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<FieldErrors>({});
  const [sending, setSending] = useState(false);
  const copy = AuthRules.FORGOT;

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    const problems = AuthRules.validateForgot(email);
    setError(null);
    setFields(problems);
    if (Object.keys(problems).length > 0) return;

    setSending(true);
    try {
      await new AuthApi().forgot(email);
      new PendingEmail().save(email);
      router.push(AuthRules.resetHref(next)); // the same next screen whether or not the address has an account
    } catch (err) {
      setError(AuthErrors.message(err));
      setFields(err instanceof ApiError ? err.fields : {});
      setSending(false);
    }
  };

  return (
    <main className="flex flex-1 items-center justify-center px-4 py-6 sm:py-10">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-[28px] border-[1.5px] border-border bg-card shadow-card min-[900px]:grid-cols-[1fr_1.05fr]">
        <BrandPanel mode="login" />

        <div className="flex flex-col gap-5 p-6 sm:p-9">
          <div className="flex flex-col gap-2">
            <span className="grid size-11 place-items-center rounded-full bg-primary-soft text-primary-text">
              <KeyRoundIcon className="size-5" aria-hidden="true" />
            </span>
            <h1 className="font-heading text-2xl font-semibold tracking-tight">{copy.title}</h1>
            <p className="text-muted-foreground">{copy.description}</p>
          </div>

          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <FormField id="email" label="Email" errors={fields.email}>
              <Input id="email" name="email" type="email" autoComplete="email" aria-invalid={!!fields.email} aria-describedby={fields.email ? "email-error" : undefined} />
            </FormField>
            <Button type="submit" size="lg" disabled={sending} className="h-11">
              {sending ? copy.pending : copy.submit}
            </Button>
          </form>

          <p className="text-center text-sm">
            <Link href={AuthRules.href("login", next)} className="font-bold underline underline-offset-4">
              {copy.back}
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
